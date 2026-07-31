"""Validate model-selected package plans and rebuild all facts from SQLite rows."""

import logging

from .package_fallback_optimizer import exact_valid_plan_exists

LOGGER = logging.getLogger(__name__)
REQUIREMENT_TO_TOTAL = {
    "data_gb": "total_data_gb",
    "local_minutes": "total_local_minutes",
    "international_minutes": "total_international_minutes",
    "sms": "total_sms",
}


def _as_dict(decision):
    if hasattr(decision, "model_dump"):
        return decision.model_dump()
    return dict(decision or {})


def _clean_text(value, fallback, limit=500):
    text = " ".join(str(value or "").split())
    return (text or fallback)[:limit]


def validate_recommendation_decision(
    decision,
    packages,
    trip_days,
    requirements,
    *,
    parsed_requirements=None,
    current_recommendation=None,
):
    payload = _as_dict(decision)
    package_map = {package.package_code: package for package in packages}
    raw_items = payload.get("package_items") or []
    raw_segments = payload.get("trip_segments") or []
    errors = []
    factual_items = []

    if not raw_items:
        errors.append("The plan does not contain any package items.")

    for raw in raw_items:
        item = _as_dict(raw)
        package_code = str(item.get("package_code") or "").strip()
        package = package_map.get(package_code)
        if package is None:
            errors.append(f"Unknown package code: {package_code or '(missing)' }.")
            continue
        if not package.active:
            errors.append(f"Package {package_code} is inactive.")
            continue
        try:
            raw_quantity = item.get("quantity")
            quantity = int(raw_quantity)
            start_day = int(item.get("coverage_start_day"))
            end_day = int(item.get("coverage_end_day"))
            activation_order = int(item.get("activation_order"))
        except (TypeError, ValueError):
            errors.append(f"Package {package_code} has invalid numeric scheduling fields.")
            continue
        if isinstance(raw_quantity, bool) or quantity != raw_quantity:
            errors.append(f"Package {package_code} quantity must be a whole number.")
            continue
        if quantity < 1 or quantity > 12:
            errors.append(f"Package {package_code} quantity must be between 1 and 12.")
            continue
        if quantity > 1 and not package.repeatable:
            errors.append(f"Package {package_code} cannot be repeated.")
            continue
        if start_day < 1 or end_day < start_day:
            errors.append(f"Package {package_code} has an invalid coverage range.")
            continue
        if end_day - start_day + 1 > package.validity_days * quantity:
            errors.append(f"Package {package_code} does not have enough validity for its assigned days.")

        factual_items.append(
            {
                "package_code": package.package_code,
                "package_name": package.name,
                "family": package.family,
                "quantity": quantity,
                "coverage_start_day": start_day,
                "coverage_end_day": end_day,
                "activation_order": activation_order,
                "assigned_segment_id": item.get("assigned_segment_id"),
                "reason_for_item": _clean_text(
                    item.get("reason_for_item"),
                    "This package contributes to the required coverage and allowances.",
                    240,
                ),
                "price_per_package_aed": float(package.price_aed),
                "validity_days_per_package": package.validity_days,
                "data_gb_per_package": float(package.data_gb),
                "local_minutes_per_package": package.local_minutes,
                "international_minutes_per_package": package.international_minutes,
                "sms_per_package": package.sms,
                "activation_code": package.activation_code,
                "preferred_network": package.preferred_network,
            }
        )

    if len(factual_items) > 1:
        for item in factual_items:
            package = package_map[item["package_code"]]
            if not package.stackable:
                errors.append(
                    f'Package {item["package_code"]} cannot be combined with other packages.'
                )

    sorted_items = sorted(factual_items, key=lambda item: (item["coverage_start_day"], item["activation_order"]))
    expected_day = 1
    activation_numbers = []
    for item in sorted_items:
        if item["coverage_start_day"] != expected_day:
            issue = "overlaps previously covered days" if item["coverage_start_day"] < expected_day else "leaves uncovered trip days"
            errors.append(f'Package {item["package_code"]} {issue}.')
        expected_day = max(expected_day, item["coverage_end_day"] + 1)
        activation_numbers.extend(
            range(item["activation_order"], item["activation_order"] + item["quantity"])
        )
    if expected_day <= trip_days:
        errors.append("The package sequence does not cover the final trip day.")
    elif expected_day != trip_days + 1:
        errors.append("Declared package coverage must end on the final trip day.")
    if activation_numbers and sorted(activation_numbers) != list(range(1, len(activation_numbers) + 1)):
        errors.append("Activation order must be continuous and start at 1.")

    segment_map = {}
    if raw_segments:
        for raw in raw_segments:
            segment = _as_dict(raw)
            try:
                start_day = int(segment.get("start_day"))
                end_day = int(segment.get("end_day"))
            except (TypeError, ValueError):
                errors.append("A trip segment has invalid day boundaries.")
                continue
            segment_id = str(segment.get("segment_id") or "").strip()
            if not segment_id or segment_id in segment_map:
                errors.append("Every trip segment must have a unique segment ID.")
                continue
            segment_map[segment_id] = {
                "segment_id": segment_id,
                "start_day": start_day,
                "end_day": end_day,
                "usage_interpretation": _clean_text(
                    segment.get("usage_interpretation"),
                    "Usage requirements for this part of the trip.",
                    300,
                ),
            }

        expected_segment_day = 1
        for segment in sorted(segment_map.values(), key=lambda item: item["start_day"]):
            if segment["start_day"] != expected_segment_day or segment["end_day"] < segment["start_day"]:
                errors.append("Trip segments must cover every day exactly once without gaps or overlaps.")
                break
            expected_segment_day = segment["end_day"] + 1
        if expected_segment_day != trip_days + 1:
            errors.append("Trip segments must end on the final trip day.")

        expected_segments = {
            segment["segment_id"]: (
                int(segment["start_day"]),
                int(segment["end_day"]),
            )
            for segment in (parsed_requirements or {}).get("segments", [])
        }
        if expected_segments:
            actual_segments = {
                segment_id: (segment["start_day"], segment["end_day"])
                for segment_id, segment in segment_map.items()
            }
            if actual_segments != expected_segments:
                errors.append(
                    "Trip segment boundaries must match the periods in the latest user instruction."
                )

        for item in factual_items:
            segment = segment_map.get(item["assigned_segment_id"])
            if segment is None:
                errors.append(f'Package {item["package_code"]} is not assigned to a valid segment.')
            elif (
                item["coverage_start_day"] < segment["start_day"]
                or item["coverage_end_day"] > segment["end_day"]
            ):
                errors.append(f'Package {item["package_code"]} falls outside its assigned segment.')

    selection = {
        "items": sorted_items,
        "total_price_aed": 0.0,
        "total_validity_days": 0,
        "unused_validity_days": 0,
        "total_data_gb": 0.0,
        "total_local_minutes": 0,
        "total_international_minutes": 0,
        "total_sms": 0,
        "activation_count": 0,
    }
    for item in factual_items:
        quantity = item["quantity"]
        selection["total_price_aed"] += item["price_per_package_aed"] * quantity
        selection["total_validity_days"] += item["validity_days_per_package"] * quantity
        selection["total_data_gb"] += item["data_gb_per_package"] * quantity
        selection["total_local_minutes"] += item["local_minutes_per_package"] * quantity
        selection["total_international_minutes"] += item["international_minutes_per_package"] * quantity
        selection["total_sms"] += item["sms_per_package"] * quantity
        selection["activation_count"] += quantity
    selection["total_price_aed"] = round(selection["total_price_aed"], 2)
    selection["total_data_gb"] = round(selection["total_data_gb"], 3)
    selection["unused_validity_days"] = max(0, selection["total_validity_days"] - trip_days)

    parsed_requirements = parsed_requirements or {}
    effective_requirements = dict(requirements)
    for metric, value in parsed_requirements.get(
        "preservation_minimums", {}
    ).items():
        if metric in REQUIREMENT_TO_TOTAL:
            effective_requirements[metric] = max(
                float(effective_requirements.get(metric, 0)),
                float(value),
            )
    for metric, total_field in REQUIREMENT_TO_TOTAL.items():
        if selection[total_field] + 1e-9 < float(
            effective_requirements.get(metric, 0)
        ):
            errors.append(f"The plan does not meet the required {metric.replace('_', ' ')}.")
    if (
        effective_requirements.get("total_call_minutes") is not None
        and selection["total_local_minutes"] + selection["total_international_minutes"] + 1e-9
        < float(effective_requirements["total_call_minutes"])
    ):
        errors.append("The plan does not meet the required total call minutes.")

    trip_wide_minimums = {
        metric: float(effective_requirements[metric])
        for metric in parsed_requirements.get("trip_wide_metrics", [])
        if metric in effective_requirements
    }
    if trip_wide_minimums and not parsed_requirements.get("segments"):
        item_fields = {
            "data_gb": "data_gb_per_package",
            "local_minutes": "local_minutes_per_package",
            "international_minutes": "international_minutes_per_package",
            "sms": "sms_per_package",
        }
        for item in factual_items:
            covered_days = item["coverage_end_day"] - item["coverage_start_day"] + 1
            share = covered_days / trip_days
            for metric, field in item_fields.items():
                if metric not in trip_wide_minimums:
                    continue
                available = item[field] * item["quantity"]
                required = trip_wide_minimums[metric] * share
                if available + 1e-9 < required:
                    errors.append(
                        f'Package {item["package_code"]} does not make the required '
                        f"{metric.replace('_', ' ')} available throughout its trip days."
                    )
            if "total_call_minutes" in trip_wide_minimums:
                available_calls = (
                    item["local_minutes_per_package"]
                    + item["international_minutes_per_package"]
                ) * item["quantity"]
                required_calls = trip_wide_minimums["total_call_minutes"] * share
                if available_calls + 1e-9 < required_calls:
                    errors.append(
                        f'Package {item["package_code"]} does not make the required '
                        "call minutes available throughout its trip days."
                    )

    maximum_price = parsed_requirements.get("maximum_price_aed")
    if maximum_price is not None and selection["total_price_aed"] > float(maximum_price) + 1e-9:
        errors.append("The plan exceeds the explicit maximum price.")
    minimum_validity = parsed_requirements.get("minimum_validity_days")
    if minimum_validity is not None and selection["total_validity_days"] < int(minimum_validity):
        errors.append("The plan does not meet the explicit minimum validity.")

    current_selection = (current_recommendation or {}).get("selection", {})
    comparative = parsed_requirements.get("comparative", [])
    comparisons = (
        ("cheaper", "total_price_aed", lambda new, old: new < old),
        ("fewer_activations", "activation_count", lambda new, old: new < old),
        ("less_data", "total_data_gb", lambda new, old: new < old),
    )
    for preference, field, predicate in comparisons:
        if (
            preference in comparative
            and current_selection.get(field) is not None
            and not predicate(selection[field], current_selection[field])
        ):
            errors.append(
                f"The plan does not fulfill the latest {preference.replace('_', ' ')} request."
            )
    if "fewer_calls" in comparative and current_selection:
        new_calls = selection["total_local_minutes"] + selection["total_international_minutes"]
        old_calls = float(current_selection.get("total_local_minutes", 0)) + float(
            current_selection.get("total_international_minutes", 0)
        )
        if new_calls >= old_calls:
            errors.append("The plan does not fulfill the latest fewer calls request.")

    allow_extra_validity = any(
        preference in comparative for preference in ("longer_validity", "fewer_activations")
    )
    if (
        selection["unused_validity_days"] > 0
        and not allow_extra_validity
        and exact_valid_plan_exists(
            packages,
            trip_days,
            effective_requirements,
            trip_wide_minimums=trip_wide_minimums,
        )
    ):
        errors.append("A reasonable exact-duration plan exists; unnecessary validity overcoverage is not allowed.")

    segment_requirements = {
        item["segment_id"]: item.get("requirements", {})
        for item in parsed_requirements.get("segments", [])
    }
    for segment_id, required in segment_requirements.items():
        segment_items = [item for item in factual_items if item["assigned_segment_id"] == segment_id]
        for metric, total_field in REQUIREMENT_TO_TOTAL.items():
            field = {
                "total_data_gb": "data_gb_per_package",
                "total_local_minutes": "local_minutes_per_package",
                "total_international_minutes": "international_minutes_per_package",
                "total_sms": "sms_per_package",
            }[total_field]
            available = sum(item[field] * item["quantity"] for item in segment_items)
            if available + 1e-9 < float(required.get(metric, 0)):
                errors.append(f"Segment {segment_id} does not meet its required {metric.replace('_', ' ')}.")

    if errors:
        LOGGER.warning("Recommendation validation failed errors=%s", errors)
        return None, errors

    LOGGER.info("Recommendation validation passed")
    segments = sorted(segment_map.values(), key=lambda item: item["start_day"])
    for segment in segments:
        segment["requirements"] = segment_requirements.get(segment["segment_id"], {})
    return {
        "segments": segments,
        "selection": selection,
        "reason": _clean_text(
            payload.get("reason") or payload.get("modification_summary"),
            "This package sequence meets the trip duration and validated usage requirements.",
        ),
        "why_it_fits": [
            _clean_text(item, "The plan meets a validated trip requirement.", 240)
            for item in (payload.get("why_it_fits") or [])[:4]
        ],
        "latest_request_interpretation": _clean_text(
            payload.get("interpreted_latest_request"),
            "No additional instruction was applied.",
            300,
        ) if parsed_requirements.get("latest_message") else None,
        "modification_summary": _clean_text(
            payload.get("modification_summary"),
            "The package plan was updated to reflect the latest instruction.",
            300,
        ) if parsed_requirements.get("latest_message") else None,
        "tradeoff_summary": _clean_text(
            payload.get("tradeoff_summary"),
            "The plan balances the requested constraints against package availability.",
            300,
        ) if payload.get("tradeoff_summary") else None,
        "source": "gemini",
    }, []
