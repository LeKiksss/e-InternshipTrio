"""System-wide exact-match history for validated roaming package plans."""

import hashlib
import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import RoamingPackage, SmartRecommendationHistory, utcnow

from .recommendation_validator import validate_recommendation_decision
from .recommendation_values import (
    METRIC_NAMES,
    canonical_decimal,
    canonical_metrics,
    canonical_string,
)


UNSPLIT_SIGNATURE = "UNSPLIT"
LOGGER = logging.getLogger(__name__)
PLAN_ITEM_FIELDS = (
    "package_code",
    "quantity",
    "coverage_start_day",
    "coverage_end_day",
    "activation_order",
    "assigned_segment_id",
)


@dataclass(frozen=True)
class SmartHistoryKey:
    data_gb: Decimal
    local_minutes: Decimal
    international_minutes: Decimal
    sms: Decimal
    period_days: int
    split: bool
    split_details: str | None
    split_signature: str

    @property
    def metrics(self):
        return {metric: getattr(self, metric) for metric in METRIC_NAMES}

    @property
    def log_fields(self):
        return {
            **{
                metric: canonical_string(getattr(self, metric), field=metric)
                for metric in METRIC_NAMES
            },
            "period_days": self.period_days,
            "split": self.split,
            "split_signature": self.split_signature,
        }


def _exact_integer(value, *, field, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer.")
    try:
        converted = int(value)
        if Decimal(str(value)) != Decimal(converted):
            raise ValueError
    except (TypeError, ValueError, ArithmeticError) as error:
        raise ValueError(f"{field} must be an integer.") from error
    if positive and converted < 1:
        raise ValueError(f"{field} must be a positive integer.")
    return converted


def _segment_metric_value(segment, metric):
    if metric in segment:
        return segment[metric]
    requirements = segment.get("requirements")
    if isinstance(requirements, dict) and metric in requirements:
        return requirements[metric]
    return None


def normalize_split_details(segments, period_days, overall_requirements=None):
    """Validate and serialize numeric split meaning without retaining raw wording."""

    period_days = _exact_integer(period_days, field="period_days", positive=True)
    if not segments:
        raise ValueError("A split must contain segments for a positive trip period.")

    normalized = []
    for raw in segments:
        if not isinstance(raw, dict):
            raise ValueError("Every split segment must be an object.")
        start_day = _exact_integer(raw.get("start_day"), field="start_day")
        end_day = _exact_integer(raw.get("end_day"), field="end_day")
        normalized.append(
            {
                "start_day": start_day,
                "end_day": end_day,
                "_raw": raw,
            }
        )

    normalized.sort(key=lambda item: (item["start_day"], item["end_day"]))
    expected_day = 1
    for segment in normalized:
        if (
            segment["start_day"] != expected_day
            or segment["end_day"] < segment["start_day"]
            or segment["end_day"] > period_days
        ):
            raise ValueError(
                "Split segments must cover every trip day exactly once without gaps or overlaps."
            )
        expected_day = segment["end_day"] + 1
    if expected_day != period_days + 1:
        raise ValueError("Split segments must end on the final trip day.")

    overall = canonical_metrics(overall_requirements) if overall_requirements else None
    for metric in METRIC_NAMES:
        provided = {}
        for index, segment in enumerate(normalized):
            value = _segment_metric_value(segment["_raw"], metric)
            if value is not None:
                provided[index] = canonical_decimal(value, field=metric)

        if overall is None and len(provided) != len(normalized):
            raise ValueError(
                f"Every segment must resolve an exact {metric.replace('_', ' ')} value."
            )

        if overall is not None:
            target = overall[metric]
            provided_total = sum(provided.values(), Decimal("0"))
            missing = [index for index in range(len(normalized)) if index not in provided]
            if provided_total > target:
                raise ValueError(
                    f"Split {metric.replace('_', ' ')} values exceed the overall requirement."
                )
            if not missing and provided_total != target:
                raise ValueError(
                    f"Split {metric.replace('_', ' ')} values must equal the overall requirement."
                )
            if missing:
                remaining = target - provided_total
                remaining_days = sum(
                    normalized[index]["end_day"]
                    - normalized[index]["start_day"]
                    + 1
                    for index in missing
                )
                allocated = Decimal("0")
                for position, index in enumerate(missing):
                    if position == len(missing) - 1:
                        value = remaining - allocated
                    else:
                        days = (
                            normalized[index]["end_day"]
                            - normalized[index]["start_day"]
                            + 1
                        )
                        value = canonical_decimal(
                            remaining * Decimal(days) / Decimal(remaining_days),
                            field=metric,
                        )
                        allocated += value
                    provided[index] = canonical_decimal(value, field=metric)

        for index, value in provided.items():
            normalized[index][metric] = canonical_string(value, field=metric)

    output = [
        {
            "start_day": segment["start_day"],
            "end_day": segment["end_day"],
            **{metric: segment[metric] for metric in METRIC_NAMES},
        }
        for segment in normalized
    ]
    return json.dumps(output, sort_keys=True, separators=(",", ":"))


def split_signature(split_details):
    if split_details is None:
        return UNSPLIT_SIGNATURE
    return hashlib.sha256(split_details.encode("utf-8")).hexdigest()


def build_history_key(requirements, period_days, segments=None):
    metrics = canonical_metrics(requirements)
    period_days = _exact_integer(period_days, field="period_days", positive=True)
    is_split = bool(segments)
    details = (
        normalize_split_details(segments, period_days, metrics)
        if is_split
        else None
    )
    return SmartHistoryKey(
        **metrics,
        period_days=period_days,
        split=is_split,
        split_details=details,
        split_signature=split_signature(details),
    )


def is_history_eligible(parsed_requirements, *, initial=False):
    """Reject requests whose decision-changing meaning is outside the exact key."""

    if initial:
        return True
    parsed = parsed_requirements or {}
    if parsed.get("restore_original"):
        return False
    if parsed.get("maximum_price_aed") is not None:
        return False
    if parsed.get("minimum_validity_days") is not None:
        return False
    if parsed.get("comparative"):
        return False
    latest_message = str(parsed.get("latest_message") or "").lower()
    if re.search(
        r"\b(?:prefer|preference|premium)\b"
        r"|\b(?:one|single)\s+package\b"
        r"|\b(?:do not|don't|avoid|exclude|without)\b[^.?!]{0,40}"
        r"\b(?:package|plan|roam with balance|roam essentials|data first|data plus|"
        r"voice first|voice plus|roam premium)\b",
        latest_message,
    ):
        return False
    return bool(parsed.get("affected_metrics") or parsed.get("segments"))


def _query_for_key(key):
    return SmartRecommendationHistory.query.filter_by(
        data_gb=key.data_gb,
        local_minutes=key.local_minutes,
        international_minutes=key.international_minutes,
        sms=key.sms,
        period_days=key.period_days,
        split=key.split,
        split_signature=key.split_signature,
    )


def structural_plan_json(plan):
    selection = (plan or {}).get("selection") or {}
    items = selection.get("items") or []
    if not items:
        raise ValueError("A validated plan must contain package items.")
    structural_items = []
    for item in items:
        structural = {field: item.get(field) for field in PLAN_ITEM_FIELDS}
        if not structural["package_code"]:
            raise ValueError("A validated plan item is missing its package code.")
        structural_items.append(structural)
    return json.dumps(
        {"items": structural_items},
        sort_keys=True,
        separators=(",", ":"),
    )


def _segments_for_validation(key):
    if not key.split_details:
        return []
    return [
        {
            "segment_id": f"segment-{index}",
            "start_day": item["start_day"],
            "end_day": item["end_day"],
            "usage_interpretation": "Numeric requirements for this trip period.",
            "requirements": {
                metric: float(canonical_decimal(item[metric], field=metric))
                for metric in METRIC_NAMES
            },
            "exact_targets": {},
        }
        for index, item in enumerate(json.loads(key.split_details), start=1)
    ]


def _rehydrate_plan(row, key, validation_requirements, parsed_requirements, current_recommendation):
    try:
        stored = json.loads(row.plan_json)
        stored_items = stored.get("items") if isinstance(stored, dict) else None
        if not isinstance(stored_items, list) or not stored_items:
            return None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    package_codes = {
        str(item.get("package_code") or "").strip()
        for item in stored_items
        if isinstance(item, dict)
    }
    packages = (
        RoamingPackage.query.filter(RoamingPackage.package_code.in_(package_codes))
        .order_by(RoamingPackage.package_code)
        .all()
    )
    split_segments = _segments_for_validation(key)
    decision = {
        "package_items": [
            {
                **{field: item.get(field) for field in PLAN_ITEM_FIELDS},
                "reason_for_item": "This package contributes to the required coverage.",
            }
            for item in stored_items
            if isinstance(item, dict)
        ],
        "trip_segments": [
            {
                "segment_id": segment["segment_id"],
                "start_day": segment["start_day"],
                "end_day": segment["end_day"],
                "usage_interpretation": segment["usage_interpretation"],
            }
            for segment in split_segments
        ],
        "reason": (
            "This package plan covers every numeric trip segment and its required services."
            if key.split
            else "This package plan covers the required trip period, data, local minutes, international minutes, and SMS."
        ),
        "why_it_fits": [],
        "interpreted_latest_request": "The numeric trip requirements were applied.",
        "modification_summary": "The package plan was updated for the requested service levels.",
        "tradeoff_summary": None,
    }
    validation_parsed = deepcopy(parsed_requirements or {})
    validation_parsed["segments"] = split_segments
    plan, errors = validate_recommendation_decision(
        decision,
        packages,
        key.period_days,
        validation_requirements,
        parsed_requirements=validation_parsed,
        current_recommendation=current_recommendation,
    )
    if errors:
        return None
    plan["source"] = "smart_history"
    return plan


def find_valid_history_plan(
    key,
    validation_requirements,
    *,
    parsed_requirements=None,
    current_recommendation=None,
):
    row = _query_for_key(key).first()
    if row is None or row.split_details != key.split_details:
        LOGGER.info("Smart History miss key=%s", key.log_fields)
        return None
    plan = _rehydrate_plan(
        row,
        key,
        validation_requirements,
        parsed_requirements,
        current_recommendation,
    )
    if plan is None:
        LOGGER.info(
            "Smart History stale-plan miss row_id=%s key=%s",
            row.id,
            key.log_fields,
        )
        return None
    row.hit_count += 1
    row.last_used_at = utcnow()
    row.updated_at = utcnow()
    db.session.commit()
    LOGGER.info(
        "Smart History hit row_id=%s key=%s",
        row.id,
        key.log_fields,
    )
    return plan


def upsert_validated_gemini_plan(key, plan):
    plan_json = structural_plan_json(plan)
    row = _query_for_key(key).first()
    if row is None:
        row = SmartRecommendationHistory(
            **key.metrics,
            period_days=key.period_days,
            split=key.split,
            split_details=key.split_details,
            split_signature=key.split_signature,
            plan_json=plan_json,
            hit_count=0,
        )
        db.session.add(row)
    else:
        row.split_details = key.split_details
        row.plan_json = plan_json
        row.updated_at = utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        row = _query_for_key(key).one()
        row.split_details = key.split_details
        row.plan_json = plan_json
        row.updated_at = utcnow()
        db.session.commit()
    LOGGER.info(
        "Smart History stored row_id=%s key=%s",
        row.id,
        key.log_fields,
    )
    return row


def smart_history_stats():
    total = SmartRecommendationHistory.query.count()
    split_entries = SmartRecommendationHistory.query.filter_by(split=True).count()
    hits = db.session.query(
        func.coalesce(func.sum(SmartRecommendationHistory.hit_count), 0)
    ).scalar()
    return {
        "total_entries": total,
        "total_hits": int(hits or 0),
        "split_entries": split_entries,
        "non_split_entries": total - split_entries,
    }


def clear_smart_history():
    removed = SmartRecommendationHistory.query.delete(synchronize_session=False)
    db.session.commit()
    return removed
