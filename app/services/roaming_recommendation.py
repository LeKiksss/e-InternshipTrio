"""End-to-end roaming recommendation orchestration."""

import hashlib
import json
import logging
from copy import deepcopy
from datetime import date

from flask import current_app

from app.models import RoamingPackage, UserMonthlyUsage

from .gemini_recommender import (
    GeminiRateLimited,
    GeminiUnavailable,
    request_recommendation_decision,
)
from .package_fallback_optimizer import optimize_package_plan
from .recommendation_validator import validate_recommendation_decision
from .usage_analysis import METRICS, build_trip_usage_analysis, calculate_trip_days
from .user_requirement_parser import merge_requirement_state, parse_user_requirements


LOGGER = logging.getLogger(__name__)
SELECTION_TOTAL_FIELDS = {
    "data_gb": "total_data_gb",
    "local_minutes": "total_local_minutes",
    "international_minutes": "total_international_minutes",
    "sms": "total_sms",
}


def _rounded_usage(values):
    return {
        "data_gb": round(float(values["data_gb"]), 3),
        "local_minutes": round(float(values["local_minutes"]), 3),
        "international_minutes": round(float(values["international_minutes"]), 3),
        "sms": round(float(values["sms"]), 3),
    }


def _rounded_requirements(values):
    rounded = _rounded_usage(values)
    if "total_call_minutes" in values:
        rounded["total_call_minutes"] = round(float(values["total_call_minutes"]), 3)
    return rounded


def _refinement_preservation_minimums(current_recommendation, latest_parsed):
    """Keep every allowance the latest message did not ask to change."""

    if (
        not latest_parsed.get("latest_message")
        or latest_parsed.get("restore_original")
        or latest_parsed.get("reset_constraints")
    ):
        return {}
    selection = (current_recommendation or {}).get("selection", {})
    if not selection:
        return {}

    affected = set(latest_parsed.get("affected_metrics", []))
    if "total_call_minutes" in affected:
        affected.update(("local_minutes", "international_minutes"))

    minimums = {}
    for metric, total_field in SELECTION_TOTAL_FIELDS.items():
        if metric in affected or selection.get(total_field) is None:
            continue
        value = float(selection[total_field])
        minimums[metric] = round(value, 3) if metric == "data_gb" else int(value)
    return minimums


def _compact_catalogue(packages):
    return [
        {
            "package_code": package.package_code,
            "family": package.family,
            "validity_days": package.validity_days,
            "price_aed": float(package.price_aed),
            "data_gb": float(package.data_gb),
            "local_minutes": package.local_minutes,
            "international_minutes": package.international_minutes,
            "sms": package.sms,
        }
        for package in packages
    ]


def _compact_current_plan(recommendation):
    selection = (recommendation or {}).get("selection", {})
    return {
        "items": [
            {
                "package_code": item.get("package_code"),
                "quantity": item.get("quantity"),
                "coverage_start_day": item.get("coverage_start_day"),
                "coverage_end_day": item.get("coverage_end_day"),
                "assigned_segment_id": item.get("assigned_segment_id"),
            }
            for item in selection.get("items", [])
        ],
        "totals": {
            key: selection.get(key)
            for key in (
                "total_price_aed",
                "total_validity_days",
                "total_data_gb",
                "total_local_minutes",
                "total_international_minutes",
                "total_sms",
                "activation_count",
            )
        },
    }


def _compact_constraints(parsed_requirements):
    return {
        "minimums": parsed_requirements.get("minimums", {}),
        "preservation_minimums": parsed_requirements.get(
            "preservation_minimums", {}
        ),
        "trip_wide_metrics": parsed_requirements.get("trip_wide_metrics", []),
        "exact_targets": parsed_requirements.get("exact_targets", {}),
        "maximum_price_aed": parsed_requirements.get("maximum_price_aed"),
        "minimum_validity_days": parsed_requirements.get("minimum_validity_days"),
        "comparative": parsed_requirements.get("comparative", []),
        "segments": parsed_requirements.get("segments", []),
        "reset_constraints": parsed_requirements.get("reset_constraints", False),
    }


def _segment_requirements(segment_descriptors, monthly_estimate):
    segments = []
    for descriptor in segment_descriptors:
        segment_days = descriptor["end_day"] - descriptor["start_day"] + 1
        modifiers = descriptor.get("modifiers", {})
        requirements = {
            "data_gb": monthly_estimate["data_gb"] * segment_days / 30 * modifiers.get("data_factor", 1.0),
            "local_minutes": monthly_estimate["local_minutes"] * segment_days / 30 * modifiers.get("local_factor", 1.0),
            "international_minutes": monthly_estimate["international_minutes"] * segment_days / 30 * modifiers.get("international_factor", 1.0),
            "sms": monthly_estimate["sms"] * segment_days / 30 * modifiers.get("sms_factor", 1.0),
        }
        segments.append(
            {
                "segment_id": descriptor["segment_id"],
                "start_day": descriptor["start_day"],
                "end_day": descriptor["end_day"],
                "usage_interpretation": descriptor["usage_interpretation"],
                "requirements": _rounded_usage(requirements),
                "exact_targets": {},
            }
        )
    return segments


def _apply_explicit_segment_targets(segments, minimums):
    """Distribute trip-wide explicit metrics while preserving segment proportions."""

    for metric in METRICS:
        if metric not in minimums or not segments:
            continue
        target = float(minimums[metric])
        existing = sum(float(segment["requirements"].get(metric, 0)) for segment in segments)
        if target == 0:
            for segment in segments:
                segment["requirements"][metric] = 0.0
                segment["exact_targets"][metric] = 0.0
            continue
        if existing > 0:
            shares = [float(segment["requirements"].get(metric, 0)) / existing for segment in segments]
        else:
            total_days = sum(segment["end_day"] - segment["start_day"] + 1 for segment in segments)
            shares = [
                (segment["end_day"] - segment["start_day"] + 1) / total_days
                for segment in segments
            ]
        allocated = 0.0
        for index, (segment, share) in enumerate(zip(segments, shares)):
            value = target - allocated if index == len(segments) - 1 else target * share
            segment["requirements"][metric] = round(value, 3)
            allocated += value


def _decision_context(
    destination,
    trip_days,
    requirements,
    packages,
    parsed_requirements,
    current_recommendation,
    conversation,
):
    context = {
        "destination": destination,
        "trip_days": trip_days,
        "trip_requirements": _rounded_requirements(requirements),
        "requirement_scope": {
            "default": "entire_trip",
            "trip_wide_metrics": parsed_requirements.get("trip_wide_metrics", []),
        },
        "active_package_catalogue": _compact_catalogue(packages),
    }
    if parsed_requirements.get("latest_message"):
        context.update(
            {
                "latest_user_instruction": parsed_requirements["latest_message"],
                "active_constraints": _compact_constraints(parsed_requirements),
                "current_plan": _compact_current_plan(current_recommendation),
                "recent_conversation": (conversation or [])[-4:],
            }
        )
    return context


def _recommendation_id(user_id, destination, start_date, end_date, selection):
    identity = json.dumps(
        {
            "user_id": user_id,
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
            "items": [
                {
                    "code": item["package_code"],
                    "quantity": item["quantity"],
                    "start": item["coverage_start_day"],
                    "end": item["coverage_end_day"],
                    "order": item["activation_order"],
                    "segment": item.get("assigned_segment_id"),
                }
                for item in selection["items"]
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _selection_signature(selection):
    return tuple(
        (
            item.get("package_code"),
            item.get("quantity"),
            item.get("coverage_start_day"),
            item.get("coverage_end_day"),
        )
        for item in (selection or {}).get("items", [])
    )


def _refinement_chat_message(
    plan,
    current_recommendation,
    *,
    gemini_rate_limited=False,
):
    changed = _selection_signature(plan.get("selection")) != _selection_signature(
        (current_recommendation or {}).get("selection")
    )
    if gemini_rate_limited and changed:
        message = (
            "The Gemini request limit was reached, so I updated the plan using "
            "the local package catalogue."
        )
    elif gemini_rate_limited:
        message = (
            "The Gemini request limit was reached, so I checked the available "
            "packages locally. Your current package is still the closest valid "
            "match, so I kept it unchanged."
        )
    elif not changed:
        message = (
            "I reviewed that request, but your current package is still the closest "
            "valid match, so I kept it unchanged."
        )
    elif plan.get("source") == "deterministic_fallback":
        message = "I updated the package plan using the available package catalogue."
    else:
        message = plan.get("modification_summary") or (
            "I updated the package plan to reflect your latest request."
        )
    tradeoff = plan.get("tradeoff_summary")
    if tradeoff and tradeoff not in message:
        message = f"{message} {tradeoff}"
    return message


def build_recommendation(
    user,
    destination,
    start_date,
    end_date,
    *,
    latest_message=None,
    current_recommendation=None,
    conversation=None,
    gemini_client=None,
    today=None,
):
    trip_days = calculate_trip_days(start_date, end_date, today=today or date.today())
    usage_rows = (
        UserMonthlyUsage.query.filter_by(user_id=user.id)
        .order_by(UserMonthlyUsage.usage_month)
        .all()
    )
    if len(usage_rows) != 6:
        raise ValueError("This account needs six months of usage history before a recommendation can be calculated.")

    usage_analysis = build_trip_usage_analysis(usage_rows, trip_days)
    requirements = dict(usage_analysis["trip_estimate"])
    latest_parsed = parse_user_requirements(
        latest_message or "",
        current_recommendation=current_recommendation,
        trip_days=trip_days,
    )
    previous_requirements = (current_recommendation or {}).get("_active_requirements", {})
    parsed = merge_requirement_state(previous_requirements, latest_parsed)
    if latest_parsed["restore_original"]:
        current_recommendation = None
        conversation = []
    parsed["preservation_minimums"] = _refinement_preservation_minimums(
        current_recommendation,
        latest_parsed,
    )
    effective_minimums = dict(parsed["minimums"])
    for metric, value in parsed["preservation_minimums"].items():
        effective_minimums[metric] = max(
            float(effective_minimums.get(metric, 0)),
            float(value),
        )
    for metric, value in effective_minimums.items():
        requirements[metric] = float(value)

    segment_descriptors = deepcopy(parsed.get("segments", []))
    segments = _segment_requirements(
        segment_descriptors,
        usage_analysis["weighted_monthly_estimate"],
    )
    _apply_explicit_segment_targets(segments, effective_minimums)
    if segments:
        for metric in METRICS:
            requirements[metric] = sum(
                float(segment["requirements"].get(metric, 0)) for segment in segments
            )
    parsed["segments"] = segments
    packages = RoamingPackage.query.filter_by(active=True).order_by(RoamingPackage.package_code).all()
    if not packages:
        raise ValueError("The package catalogue is temporarily unavailable.")

    context = _decision_context(
        destination,
        trip_days,
        requirements,
        packages,
        parsed,
        current_recommendation,
        conversation,
    )

    plan = None
    gemini_rate_limited = False
    api_key = current_app.config.get("GEMINI_API_KEY", "")
    model = current_app.config.get("GEMINI_MODEL", "gemini-3.5-flash")
    timeout = current_app.config.get("GEMINI_TIMEOUT_SECONDS", 45)
    rate_limit_cooldown = current_app.config.get(
        "GEMINI_RATE_LIMIT_COOLDOWN_SECONDS",
        60,
    )
    request_log_dir = current_app.config.get("GEMINI_REQUEST_LOG_DIR")
    try:
        decision = request_recommendation_decision(
            context,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout,
            client=gemini_client,
            request_log_dir=request_log_dir,
            rate_limit_cooldown_seconds=rate_limit_cooldown,
        )
        plan, errors = validate_recommendation_decision(
            decision,
            packages,
            trip_days,
            requirements,
            parsed_requirements=parsed,
            current_recommendation=current_recommendation,
        )
        if errors:
            LOGGER.info("Correction retry started")
            corrected = request_recommendation_decision(
                context,
                api_key=api_key,
                model=model,
                timeout_seconds=timeout,
                client=gemini_client,
                invalid_decision=(
                    decision.model_dump()
                    if hasattr(decision, "model_dump")
                    else dict(decision)
                ),
                validation_errors=errors,
                request_log_dir=request_log_dir,
                rate_limit_cooldown_seconds=rate_limit_cooldown,
            )
            plan, errors = validate_recommendation_decision(
                corrected,
                packages,
                trip_days,
                requirements,
                parsed_requirements=parsed,
                current_recommendation=current_recommendation,
            )
            if errors:
                raise GeminiUnavailable("Gemini did not return a valid corrected plan.")
    except GeminiUnavailable as error:
        gemini_rate_limited = isinstance(error, GeminiRateLimited)
        LOGGER.info("Deterministic fallback used")
        plan = optimize_package_plan(
            packages,
            trip_days,
            requirements,
            exact_targets=parsed["exact_targets"],
            preferences=parsed["comparative"],
            maximum_price_aed=parsed["maximum_price_aed"],
            minimum_validity_days=parsed["minimum_validity_days"],
            segments=segments,
            current_selection=(current_recommendation or {}).get("selection"),
            trip_wide_minimums={
                metric: requirements[metric]
                for metric in parsed.get("trip_wide_metrics", [])
                if metric in requirements
            } if not segments else None,
        )
        plan["latest_request_interpretation"] = (
            parsed["interpretation"] if parsed["latest_message"] else None
        )
        plan["modification_summary"] = (
            "The available package options were reviewed against the latest instruction."
            if parsed["latest_message"]
            else None
        )

    response = {
        "recommendation_id": _recommendation_id(
            user.id,
            destination,
            start_date,
            end_date,
            plan["selection"],
        ),
        "destination": destination,
        "trip": {
            "start_date": start_date,
            "end_date": end_date,
            "trip_days": trip_days,
        },
        "usage_analysis": {
            "pattern": usage_analysis["pattern_classification"],
            "outliers_detected": usage_analysis["excluded_outliers"],
            "monthly_estimate": _rounded_usage(usage_analysis["weighted_monthly_estimate"]),
            "trip_estimate": _rounded_usage(usage_analysis["trip_estimate"]),
            "requirements": _rounded_requirements(requirements),
            "explanation": usage_analysis["explanation"],
        },
        "segments": plan.get("segments", []),
        "selection": plan["selection"],
        "reason": plan["reason"],
        "why_it_fits": plan.get("why_it_fits", []),
        "latest_request_interpretation": plan.get("latest_request_interpretation"),
        "modification_summary": plan.get("modification_summary"),
        "tradeoff_summary": plan.get("tradeoff_summary"),
        "source": plan.get("source", "gemini"),
        "gemini_rate_limited": gemini_rate_limited,
        "_active_requirements": {
            **deepcopy(parsed),
            "segments": segment_descriptors,
        },
    }
    if parsed.get("latest_message"):
        response["chat_message"] = _refinement_chat_message(
            plan,
            current_recommendation,
            gemini_rate_limited=gemini_rate_limited,
        )
        response["modification_summary"] = response["chat_message"]
    return response
