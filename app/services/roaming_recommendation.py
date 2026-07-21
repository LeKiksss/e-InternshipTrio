"""End-to-end roaming recommendation orchestration."""

import hashlib
import json
import logging
from copy import deepcopy
from datetime import date

from flask import current_app

from app.models import RoamingPackage, UserMonthlyUsage

from .gemini_recommender import GeminiUnavailable, request_recommendation_decision
from .package_fallback_optimizer import optimize_package_plan
from .recommendation_validator import validate_recommendation_decision
from .usage_analysis import METRICS, build_trip_usage_analysis, calculate_trip_days
from .user_requirement_parser import merge_requirement_state, parse_user_requirements


LOGGER = logging.getLogger(__name__)


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
    user,
    destination,
    start_date,
    end_date,
    trip_days,
    usage_analysis,
    requirements,
    packages,
    parsed_requirements,
    current_recommendation,
    conversation,
):
    context = {
        "anonymous_user_id": user.id,
        "destination": destination,
        "trip": {
            "start_date": start_date,
            "end_date": end_date,
            "trip_days": trip_days,
        },
        "raw_monthly_usage": usage_analysis["raw_monthly_usage"],
        "detected_outliers": usage_analysis["excluded_outliers"],
        "usage_analysis_policy": usage_analysis["outlier_policy"],
        "pattern_classification": usage_analysis["pattern_classification"],
        "recency_weights": [0.10, 0.12, 0.15, 0.18, 0.20, 0.25],
        "weighted_monthly_profile": _rounded_usage(usage_analysis["weighted_monthly_estimate"]),
        "trip_requirements": _rounded_requirements(requirements),
        "active_package_catalogue": [package.to_catalog_dict() for package in packages],
        "recommendation_priorities": [
            "meet duration and usage requirements",
            "respect temporal segments",
            "prefer practical exact-duration coverage",
            "minimize unused validity",
            "minimize price",
            "minimize allowance waste",
            "minimize activations when earlier factors are comparable",
        ],
        "activation_practicality": "Three activations are reasonable for a normal 23-day trip.",
    }
    if parsed_requirements.get("latest_message"):
        context.update(
            {
                "current_validated_recommendation": current_recommendation,
                "conversation_history": conversation or [],
                "parsed_requirements": parsed_requirements,
                "latest_user_message": parsed_requirements["latest_message"],
                "HIGHEST_PRIORITY_LATEST_USER_INSTRUCTION": parsed_requirements["latest_message"],
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
    for metric, value in parsed["minimums"].items():
        requirements[metric] = float(value)

    segment_descriptors = deepcopy(parsed.get("segments", []))
    segments = _segment_requirements(
        segment_descriptors,
        usage_analysis["weighted_monthly_estimate"],
    )
    _apply_explicit_segment_targets(segments, parsed["minimums"])
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
        user,
        destination,
        start_date,
        end_date,
        trip_days,
        usage_analysis,
        requirements,
        packages,
        parsed,
        current_recommendation,
        conversation,
    )

    plan = None
    api_key = current_app.config.get("GEMINI_API_KEY", "")
    model = current_app.config.get("GEMINI_MODEL", "gemini-3.5-flash")
    timeout = current_app.config.get("GEMINI_TIMEOUT_SECONDS", 30)
    request_log_dir = current_app.config.get("GEMINI_REQUEST_LOG_DIR")
    try:
        decision = request_recommendation_decision(
            context,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout,
            client=gemini_client,
            request_log_dir=request_log_dir,
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
    except GeminiUnavailable:
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
        )
        plan["latest_request_interpretation"] = (
            parsed["interpretation"] if parsed["latest_message"] else None
        )
        plan["modification_summary"] = (
            "The plan was recalculated to reflect the latest instruction."
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
        "_active_requirements": {
            **deepcopy(parsed),
            "segments": segment_descriptors,
        },
    }
    return response
