"""Deterministic monthly usage analysis and trip requirement calculations."""

import logging
import statistics
from datetime import date


LOGGER = logging.getLogger(__name__)
METRICS = ("data_gb", "local_minutes", "international_minutes", "sms")
RECENCY_WEIGHTS = (0.10, 0.12, 0.15, 0.18, 0.20, 0.25)
OUTLIER_CHANGE_THRESHOLD = 0.30


def _month_label(record):
    value = record.usage_month
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _record_value(record, metric):
    return float(getattr(record, metric))


def _sustained_direction(values):
    changes = [right - left for left, right in zip(values, values[1:])]
    positive = sum(change > 0 for change in changes)
    negative = sum(change < 0 for change in changes)
    direction = "upward_trend" if positive >= 4 else "downward_trend" if negative >= 4 else None
    if direction is None:
        return None

    absolute_changes = [abs(change) for change in changes]
    typical = statistics.median(absolute_changes) or max(absolute_changes, default=0)
    if typical:
        for index, change in enumerate(changes):
            if abs(change) <= typical * 4:
                continue
            neighbours = changes[max(0, index - 1) : index] + changes[index + 1 : index + 2]
            if any(
                change * neighbour < 0 and abs(neighbour) >= abs(change) * 0.5
                for neighbour in neighbours
            ):
                return None

    if direction == "upward_trend" and values[-1] <= values[0]:
        return None
    if direction == "downward_trend" and values[-1] >= values[0]:
        return None
    return direction


def _relative_change(previous, current):
    if previous == 0:
        return 0.0 if current == 0 else 1.0
    return (current - previous) / abs(previous)


def _successive_changes(values):
    return [
        _relative_change(previous, current)
        for previous, current in zip(values, values[1:])
    ]


def _outlier_candidates(successive_changes):
    """Find isolated turning months using only adjacent-month comparisons."""

    exceeds_threshold = [
        abs(change) > OUTLIER_CHANGE_THRESHOLD for change in successive_changes
    ]
    candidates = set()
    turning_scores = {}

    # An interior spike or dip changes direction around the unusual month. At
    # least one of the two adjacent comparisons must exceed the 30% threshold.
    for month_index in range(1, len(successive_changes)):
        incoming = successive_changes[month_index - 1]
        outgoing = successive_changes[month_index]
        if incoming * outgoing < 0 and (
            exceeds_threshold[month_index - 1]
            or exceeds_threshold[month_index]
        ):
            turning_scores[month_index] = sum(
                (
                    exceeds_threshold[month_index - 1],
                    exceeds_threshold[month_index],
                )
            )

    # Prefer the turning point bounded by two large changes over the adjacent
    # rebound month, which may reverse direction by only a small amount.
    if turning_scores:
        strongest_score = max(turning_scores.values())
        candidates.update(
            index
            for index, score in turning_scores.items()
            if score == strongest_score
        )

    # At either edge there is only one neighbouring month. Treat the edge as
    # isolated when that one large change is not part of another large step.
    if exceeds_threshold and exceeds_threshold[0] and (
        len(exceeds_threshold) == 1
        or (
            not exceeds_threshold[1]
            and successive_changes[0] * successive_changes[1] >= 0
        )
    ):
        candidates.add(0)
    if exceeds_threshold and exceeds_threshold[-1] and (
        len(exceeds_threshold) == 1
        or (
            not exceeds_threshold[-2]
            and successive_changes[-1] * successive_changes[-2] >= 0
        )
    ):
        candidates.add(len(successive_changes))

    return sorted(candidates)


def analyse_usage(records):
    """Analyse six chronological raw usage rows without mutating the records."""

    ordered = sorted(records, key=lambda row: row.usage_month)
    if len(ordered) != 6:
        raise ValueError("Exactly six monthly usage records are required.")

    LOGGER.info("Usage analysis started for user_id=%s", ordered[0].user_id)
    metric_results = {}
    excluded_outliers = []
    weighted_estimate = {}

    for metric in METRICS:
        values = [_record_value(record, metric) for record in ordered]
        successive_changes = _successive_changes(values)
        excluded = _outlier_candidates(successive_changes)
        trend = None if excluded else _sustained_direction(values)
        detected_pattern = "isolated_outlier" if excluded else (trend or "stable")

        effective_weights = list(RECENCY_WEIGHTS)
        for index in excluded:
            effective_weights[index] = 0.0
        total_weight = sum(effective_weights)
        effective_weights = [weight / total_weight for weight in effective_weights]
        estimate = sum(value * weight for value, weight in zip(values, effective_weights))
        weighted_estimate[metric] = estimate

        excluded_months = [_month_label(ordered[index]) for index in excluded]
        for index in excluded:
            item = {
                "metric": metric,
                "usage_month": _month_label(ordered[index]),
                "value": values[index],
            }
            excluded_outliers.append(item)
            LOGGER.info(
                "Isolated outlier identified metric=%s month=%s",
                metric,
                item["usage_month"],
            )

        metric_results[metric] = {
            "raw_values": values,
            "successive_month_changes": [
                {
                    "from_month": _month_label(ordered[index]),
                    "to_month": _month_label(ordered[index + 1]),
                    "change_percent": change * 100,
                    "exceeds_outlier_threshold": (
                        abs(change) > OUTLIER_CHANGE_THRESHOLD
                    ),
                }
                for index, change in enumerate(successive_changes)
            ],
            "excluded_months": excluded_months,
            "effective_weights": effective_weights,
            "weighted_estimate": estimate,
            "detected_pattern": detected_pattern,
        }

    patterns = [result["detected_pattern"] for result in metric_results.values()]
    if patterns.count("upward_trend") >= 2:
        classification = "upward_trend"
    elif patterns.count("downward_trend") >= 2:
        classification = "downward_trend"
    elif "isolated_outlier" in patterns:
        classification = "isolated_outlier"
    else:
        classification = "stable"

    LOGGER.info("Pattern classification calculated pattern=%s", classification)
    explanation = {
        "stable": "Recent usage is consistent across the observed months.",
        "isolated_outlier": (
            "Usage changed by more than 30% between successive months and reversed around an "
            "isolated month; that month was excluded per metric while the raw record was preserved."
        ),
        "upward_trend": (
            "Recent usage shows a sustained increase; all observed months retain their recency weights."
        ),
        "downward_trend": (
            "Recent usage shows a sustained decrease; all observed months retain their recency weights."
        ),
    }[classification]

    return {
        "raw_monthly_usage": [record.to_dict() for record in ordered],
        "outlier_policy": {
            "method": "successive_month_comparison",
            "threshold_percent": OUTLIER_CHANGE_THRESHOLD * 100,
            "excluded_values_used_for_profile": False,
        },
        "metric_results": metric_results,
        "excluded_outliers": excluded_outliers,
        "weighted_monthly_estimate": weighted_estimate,
        "pattern_classification": classification,
        "explanation": explanation,
    }


def calculate_trip_days(start_date, end_date, today=None):
    try:
        start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    except (TypeError, ValueError) as error:
        raise ValueError("Enter valid travel dates.") from error
    if not isinstance(start, date) or not isinstance(end, date):
        raise ValueError("Enter valid travel dates.")
    if end < start:
        raise ValueError("Return date must be on or after the departure date.")
    if today is not None and start < today:
        raise ValueError("Choose travel dates in the future.")
    return (end - start).days + 1


def scale_usage_to_trip(monthly_estimate, trip_days):
    if not isinstance(trip_days, int) or trip_days < 1:
        raise ValueError("Trip duration must be at least one day.")
    return {
        metric: float(monthly_estimate[metric]) * trip_days / 30
        for metric in METRICS
    }


def build_trip_usage_analysis(records, trip_days):
    result = analyse_usage(records)
    trip_estimate = scale_usage_to_trip(result["weighted_monthly_estimate"], trip_days)
    result["trip_estimate"] = trip_estimate
    return result
