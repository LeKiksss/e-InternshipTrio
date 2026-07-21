"""Bounded deterministic optimizer used when Gemini cannot provide a valid plan."""

import math
from collections import defaultdict


METRIC_FIELDS = {
    "data_gb": "data_gb",
    "local_minutes": "local_minutes",
    "international_minutes": "international_minutes",
    "sms": "sms",
}


def _value(package, field):
    value = getattr(package, field)
    return float(value) if field in {"data_gb", "price_aed"} else int(value)


def _empty_totals():
    return {
        "data_gb": 0.0,
        "local_minutes": 0,
        "international_minutes": 0,
        "sms": 0,
        "price_aed": 0.0,
        "validity_days": 0,
    }


def _add_package(totals, package):
    updated = totals.copy()
    for metric, field in METRIC_FIELDS.items():
        updated[metric] += _value(package, field)
    updated["price_aed"] += _value(package, "price_aed")
    updated["validity_days"] += package.validity_days
    return updated


def _meets(totals, requirements, maximum_price_aed=None, minimum_validity_days=None):
    if any(totals[metric] + 1e-9 < float(requirements.get(metric, 0)) for metric in METRIC_FIELDS):
        return False
    if maximum_price_aed is not None and totals["price_aed"] > maximum_price_aed + 1e-9:
        return False
    if minimum_validity_days is not None and totals["validity_days"] < minimum_validity_days:
        return False
    if (
        requirements.get("total_call_minutes") is not None
        and totals["local_minutes"] + totals["international_minutes"] + 1e-9
        < float(requirements["total_call_minutes"])
    ):
        return False
    return True


def _normalized_waste(totals, requirements, exact_targets):
    waste = 0.0
    for metric in METRIC_FIELDS:
        target = float(exact_targets.get(metric, requirements.get(metric, 0)))
        if target > 0:
            waste += max(0.0, totals[metric] - target) / target
        elif metric in exact_targets:
            waste += totals[metric]
    call_target = float(
        exact_targets.get(
            "total_call_minutes",
            requirements.get("total_call_minutes", 0),
        )
    )
    if call_target > 0:
        total_calls = totals["local_minutes"] + totals["international_minutes"]
        waste += max(0.0, total_calls - call_target) / call_target
    return waste


def _meets_comparative_preferences(candidate, preferences, current_selection):
    if not current_selection:
        return True
    totals = candidate["totals"]
    checks = {
        "cheaper": totals["price_aed"] < float(current_selection.get("total_price_aed", float("inf"))),
        "less_data": totals["data_gb"] < float(current_selection.get("total_data_gb", float("inf"))),
        "fewer_calls": (
            totals["local_minutes"] + totals["international_minutes"]
            < float(current_selection.get("total_local_minutes", 0))
            + float(current_selection.get("total_international_minutes", 0))
        ),
        "fewer_activations": len(candidate["packages"])
        < int(current_selection.get("activation_count", 10**6)),
        "longer_validity": totals["validity_days"]
        > int(current_selection.get("total_validity_days", 0)),
    }
    return all(checks[preference] for preference in preferences if preference in checks)


def _candidate_score(candidate, trip_days, requirements, exact_targets, preferences):
    totals = candidate["totals"]
    duration_waste = max(0, totals["validity_days"] - trip_days)
    allowance_waste = _normalized_waste(totals, requirements, exact_targets)
    activations = len(candidate["packages"])
    price = totals["price_aed"]
    focus_score = 0.0
    if "focus_calls" in preferences:
        focus_score -= (
            totals["local_minutes"] + totals["international_minutes"]
        ) / max(price, 1.0)
    if "focus_data" in preferences:
        focus_score -= totals["data_gb"] / max(price, 1.0)
    if "focus_sms" in preferences:
        focus_score -= totals["sms"] / max(price, 1.0)
    if "fewer_activations" in preferences:
        return duration_waste, activations, price, allowance_waste
    if any(preference.startswith("focus_") for preference in preferences):
        if "cheaper" in preferences or "budget_limited" in preferences:
            return duration_waste, price, focus_score, allowance_waste, activations
        return duration_waste, focus_score, price, allowance_waste, activations
    return duration_waste, price, allowance_waste, activations


def _partial_score(candidate, requirements):
    totals = candidate["totals"]
    deficit = sum(
        max(0.0, float(requirements.get(metric, 0)) - totals[metric])
        / max(float(requirements.get(metric, 0)), 1.0)
        for metric in METRIC_FIELDS
    )
    return deficit, totals["price_aed"], len(candidate["packages"])


def _coverage_allocations(packages, coverage_days):
    if len(packages) > coverage_days:
        raise ValueError("Every package activation needs at least one covered travel day.")

    remaining_days = coverage_days
    allocations = []
    for index, package in enumerate(packages):
        remaining_activations = len(packages) - index - 1
        covered_days = min(
            package.validity_days,
            remaining_days - remaining_activations,
        )
        if covered_days < 1:
            raise ValueError("The selected activations cannot be scheduled within the trip.")
        allocations.append(covered_days)
        remaining_days -= covered_days
    if remaining_days:
        raise ValueError("The selected package validity does not cover the requested period.")
    return allocations


def _supports_trip_wide_minimums(packages, trip_days, trip_wide_minimums):
    if not trip_wide_minimums:
        return True
    try:
        allocations = _coverage_allocations(packages, trip_days)
    except ValueError:
        return False

    for package, covered_days in zip(packages, allocations):
        share = covered_days / trip_days
        for metric, field in METRIC_FIELDS.items():
            required = float(trip_wide_minimums.get(metric, 0)) * share
            if _value(package, field) + 1e-9 < required:
                return False
        if "total_call_minutes" in trip_wide_minimums:
            required_calls = float(trip_wide_minimums["total_call_minutes"]) * share
            available_calls = package.local_minutes + package.international_minutes
            if available_calls + 1e-9 < required_calls:
                return False
    return True


def _search(
    packages,
    trip_days,
    requirements,
    exact_targets,
    preferences,
    maximum_price_aed=None,
    minimum_validity_days=None,
    exact_only=False,
    current_selection=None,
    enforce_comparatives=True,
    trip_wide_minimums=None,
):
    active = sorted(
        (
            package
            for package in packages
            if package.active and package.repeatable and package.stackable
        ),
        key=lambda package: package.package_code,
    )
    if not active:
        raise ValueError("No active roaming packages are available.")

    max_activations = min(8, max(3, math.ceil(trip_days / 7) + 2))
    max_coverage = trip_days if exact_only else trip_days + max(package.validity_days for package in active) - 1
    frontier = [{"packages": [], "totals": _empty_totals(), "last_index": 0}]
    completed = []

    for _activation in range(max_activations):
        grouped = defaultdict(list)
        for candidate in frontier:
            # Every activation must be assigned at least one actual travel day.
            if len(candidate["packages"]) >= trip_days:
                continue
            for package_index in range(candidate["last_index"], len(active)):
                package = active[package_index]
                totals = _add_package(candidate["totals"], package)
                if totals["validity_days"] > max_coverage:
                    continue
                next_candidate = {
                    "packages": [*candidate["packages"], package],
                    "totals": totals,
                    "last_index": package_index,
                }
                if totals["validity_days"] >= trip_days and _meets(
                    totals,
                    requirements,
                    maximum_price_aed,
                    minimum_validity_days,
                ) and _supports_trip_wide_minimums(
                    next_candidate["packages"],
                    trip_days,
                    trip_wide_minimums,
                ) and (
                    not enforce_comparatives
                    or _meets_comparative_preferences(
                        next_candidate,
                        preferences,
                        current_selection,
                    )
                ):
                    completed.append(next_candidate)
                if totals["validity_days"] < max_coverage:
                    grouped[totals["validity_days"]].append(next_candidate)

        frontier = []
        for candidates in grouped.values():
            unique = {}
            for candidate in candidates:
                signature = tuple(package.package_code for package in candidate["packages"])
                current = unique.get(signature)
                if current is None or _partial_score(candidate, requirements) < _partial_score(current, requirements):
                    unique[signature] = candidate
            frontier.extend(sorted(unique.values(), key=lambda item: _partial_score(item, requirements))[:180])
        if not frontier and completed:
            break

    if not completed:
        raise ValueError("No package combination can satisfy the trip requirements.")
    return min(
        completed,
        key=lambda item: _candidate_score(
            item,
            trip_days,
            requirements,
            exact_targets,
            preferences,
        ),
    )


def _compress_items(
    packages,
    day_offset=0,
    segment_id=None,
    interpretation=None,
    coverage_days=None,
):
    """Assign every activation to real trip days and combine safe repeats."""

    coverage_days = coverage_days or sum(package.validity_days for package in packages)
    allocations = _coverage_allocations(packages, coverage_days)

    items = []
    coverage_cursor = day_offset + 1
    activation_order = 1
    previous_repeat_is_mergeable = False
    for package, covered_days in zip(packages, allocations):
        coverage_end = coverage_cursor + covered_days - 1
        if (
            items
            and items[-1]["package_code"] == package.package_code
            and previous_repeat_is_mergeable
        ):
            items[-1]["quantity"] += 1
            items[-1]["coverage_end_day"] = coverage_end
        else:
            items.append(
                {
                    "package_code": package.package_code,
                    "package_name": package.name,
                    "family": package.family,
                    "quantity": 1,
                    "coverage_start_day": coverage_cursor,
                    "coverage_end_day": coverage_end,
                    "activation_order": activation_order,
                    "assigned_segment_id": segment_id,
                    "reason_for_item": interpretation or PACKAGE_REASON.get(
                        package.category,
                        "Provides the required trip coverage and allowances.",
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
        previous_repeat_is_mergeable = covered_days == package.validity_days
        coverage_cursor = coverage_end + 1
        activation_order += 1
    return items


PACKAGE_REASON = {
    "BUDGET_BALANCED": "Keeps cost controlled while covering balanced usage.",
    "BALANCED": "Balances data, calls, and messaging for this period.",
    "PREMIUM_BALANCED": "Covers intensive mixed usage without allowance gaps.",
    "DATA_MAXIMUM": "Provides the strongest data allowance for this period.",
    "DATA_FOCUSED": "Prioritizes data while retaining practical call allowances.",
    "VOICE_MAXIMUM": "Provides the strongest voice allowances for this period.",
    "VOICE_FOCUSED": "Prioritizes calls while retaining useful data.",
}


def _selection_from_items(items, trip_days):
    selection = {
        "items": items,
        "total_price_aed": 0.0,
        "total_validity_days": 0,
        "unused_validity_days": 0,
        "total_data_gb": 0.0,
        "total_local_minutes": 0,
        "total_international_minutes": 0,
        "total_sms": 0,
        "activation_count": 0,
    }
    for item in items:
        quantity = item["quantity"]
        selection["total_price_aed"] += item["price_per_package_aed"] * quantity
        selection["total_validity_days"] += item["validity_days_per_package"] * quantity
        selection["total_data_gb"] += item["data_gb_per_package"] * quantity
        selection["total_local_minutes"] += item["local_minutes_per_package"] * quantity
        selection["total_international_minutes"] += item["international_minutes_per_package"] * quantity
        selection["total_sms"] += item["sms_per_package"] * quantity
        selection["activation_count"] += quantity
    selection["unused_validity_days"] = max(0, selection["total_validity_days"] - trip_days)
    selection["total_price_aed"] = round(selection["total_price_aed"], 2)
    selection["total_data_gb"] = round(selection["total_data_gb"], 3)
    return selection


def optimize_package_plan(
    packages,
    trip_days,
    requirements,
    *,
    exact_targets=None,
    preferences=None,
    maximum_price_aed=None,
    minimum_validity_days=None,
    segments=None,
    exact_only=False,
    current_selection=None,
    trip_wide_minimums=None,
):
    """Return a valid package selection using a bounded duration DP/beam search."""

    exact_targets = exact_targets or {}
    preferences = preferences or []
    segments = segments or []
    all_items = []
    rendered_segments = []
    relaxed_constraints = []

    if segments:
        activation_offset = 0
        maximum_extra_per_segment = max(package.validity_days for package in packages) - 1
        extra_validity = max(0, int(minimum_validity_days or trip_days) - trip_days)
        segment_extra = [0] * len(segments)
        for index in range(len(segments) - 1, -1, -1):
            allocated = min(extra_validity, maximum_extra_per_segment)
            segment_extra[index] = allocated
            extra_validity -= allocated
        if extra_validity:
            relaxed_constraints.append("minimum validity")

        for segment_index, segment in enumerate(segments):
            segment_days = segment["end_day"] - segment["start_day"] + 1
            requested_segment_validity = segment_days + segment_extra[segment_index]
            try:
                candidate = _search(
                    packages,
                    segment_days,
                    segment["requirements"],
                    segment.get("exact_targets", {}),
                    preferences,
                    maximum_price_aed=None,
                    minimum_validity_days=requested_segment_validity,
                    exact_only=segment_extra[segment_index] == 0,
                )
            except ValueError:
                if not segment_extra[segment_index]:
                    raise
                relaxed_constraints.append("minimum validity")
                candidate = _search(
                    packages,
                    segment_days,
                    segment["requirements"],
                    segment.get("exact_targets", {}),
                    preferences,
                    maximum_price_aed=None,
                    exact_only=True,
                )
            items = _compress_items(
                candidate["packages"],
                day_offset=segment["start_day"] - 1,
                segment_id=segment["segment_id"],
                interpretation=segment["usage_interpretation"],
                coverage_days=segment_days,
            )
            for item in items:
                item["activation_order"] += activation_offset
            activation_offset += sum(item["quantity"] for item in items)
            all_items.extend(items)
            rendered_segments.append(
                {
                    "segment_id": segment["segment_id"],
                    "start_day": segment["start_day"],
                    "end_day": segment["end_day"],
                    "usage_interpretation": segment["usage_interpretation"],
                    "requirements": segment["requirements"],
                }
            )
    else:
        attempts = [
            (maximum_price_aed, minimum_validity_days, True, []),
            (maximum_price_aed, minimum_validity_days, False, ["relative preference"]),
        ]
        if maximum_price_aed is not None:
            attempts.extend(
                [
                    (None, minimum_validity_days, True, ["maximum price"]),
                    (None, minimum_validity_days, False, ["maximum price", "relative preference"]),
                ]
            )
        if minimum_validity_days is not None:
            attempts.extend(
                [
                    (maximum_price_aed, None, True, ["minimum validity"]),
                    (maximum_price_aed, None, False, ["minimum validity", "relative preference"]),
                ]
            )
        if maximum_price_aed is not None and minimum_validity_days is not None:
            attempts.extend(
                [
                    (None, None, True, ["maximum price", "minimum validity"]),
                    (None, None, False, ["maximum price", "minimum validity", "relative preference"]),
                ]
            )
        candidate = None
        for price_limit, validity_limit, enforce_comparatives, relaxed in attempts:
            try:
                candidate = _search(
                    packages,
                    trip_days,
                    requirements,
                    exact_targets,
                    preferences,
                    price_limit,
                    validity_limit,
                    exact_only=exact_only,
                    current_selection=current_selection,
                    enforce_comparatives=enforce_comparatives,
                    trip_wide_minimums=trip_wide_minimums,
                )
                relaxed_constraints = relaxed
                break
            except ValueError:
                continue
        if candidate is None:
            raise ValueError("No package combination can satisfy the trip requirements.")
        all_items = _compress_items(candidate["packages"], coverage_days=trip_days)

    selection = _selection_from_items(all_items, trip_days)
    if maximum_price_aed is not None and selection["total_price_aed"] > maximum_price_aed + 1e-9:
        relaxed_constraints.append("maximum price")
    if minimum_validity_days is not None and selection["total_validity_days"] < minimum_validity_days:
        relaxed_constraints.append("minimum validity")
    if segments and current_selection and not _meets_comparative_preferences(
        {
            "packages": [None] * selection["activation_count"],
            "totals": {
                "price_aed": selection["total_price_aed"],
                "data_gb": selection["total_data_gb"],
                "local_minutes": selection["total_local_minutes"],
                "international_minutes": selection["total_international_minutes"],
                "validity_days": selection["total_validity_days"],
            },
        },
        preferences,
        current_selection,
    ):
        relaxed_constraints.append("relative preference")
    return {
        "segments": rendered_segments,
        "selection": selection,
        "reason": (
            "The selected sequence covers every travel day and meets the validated usage requirements "
            "with a close duration and cost fit."
        ),
        "why_it_fits": [
            f'{selection["total_validity_days"]} days of combined validity cover the {trip_days}-day trip.',
            f'AED {selection["total_price_aed"]:g} is the lowest-ranked valid duration fit found.',
        ],
        "tradeoff_summary": (
            "The closest valid plan was used because the "
            + " and ".join(dict.fromkeys(relaxed_constraints))
            + " could not be satisfied together with the trip requirements."
            if relaxed_constraints
            else None
        ),
        "source": "deterministic_fallback",
    }


def exact_valid_plan_exists(
    packages,
    trip_days,
    requirements,
    *,
    trip_wide_minimums=None,
):
    try:
        optimize_package_plan(
            packages,
            trip_days,
            requirements,
            exact_only=True,
            trip_wide_minimums=trip_wide_minimums,
        )
        return True
    except ValueError:
        return False
