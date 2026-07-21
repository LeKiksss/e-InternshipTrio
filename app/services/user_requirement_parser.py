"""Deterministic extraction of explicit roaming-plan requirements."""

from copy import deepcopy
import math
import re


def _number(pattern, text):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _current_totals(current_recommendation):
    return (current_recommendation or {}).get("selection", {})


def parse_user_requirements(message, current_recommendation=None, trip_days=None):
    text = " ".join((message or "").strip().split())
    lowered = text.lower()
    minimums = {}
    exact_targets = {}
    comparative = []
    affected_metrics = set()

    data = _number(r"(?:at least\s+|minimum\s+|need\s+|only\s+need\s+)?(\d+(?:\.\d+)?)\s*gb\b", text)
    international = _number(
        r"(?:at least\s+|minimum\s+|need\s+)?(\d+)\s+(?:international\s+)(?:call\s+)?minutes?\b",
        text,
    )
    local = _number(
        r"(?:at least\s+|minimum\s+|need\s+)?(\d+)\s+(?:local\s+)(?:call\s+)?minutes?\b",
        text,
    )
    general_calls = _number(
        r"(?:at least\s+|minimum\s+|need\s+)?(\d+)\s+(?:(?:call|voice)\s+)?minutes?\b",
        text,
    )
    sms = _number(r"(?:at least\s+|minimum\s+|need\s+)?(\d+)\s*(?:sms|texts?)\b", text)
    maximum_price = _number(
        r"(?:no more than|maximum|max|under|up to)\s*(?:aed\s*)?(\d+(?:\.\d+)?)",
        text,
    )
    if maximum_price is None:
        maximum_price = _number(r"aed\s*(\d+(?:\.\d+)?)\s*(?:maximum|max|or less)?", text)
    minimum_validity = _number(r"(?:at least|minimum|need)\s+(\d+)\s+days?\s+(?:of\s+)?validity", text)

    if data is not None:
        minimums["data_gb"] = data
        affected_metrics.add("data_gb")
        if "only" in lowered:
            exact_targets["data_gb"] = data
    if international is not None:
        minimums["international_minutes"] = international
        affected_metrics.add("international_minutes")
    if local is not None:
        minimums["local_minutes"] = local
        affected_metrics.add("local_minutes")
    if general_calls is not None and international is None and local is None:
        minimums["total_call_minutes"] = general_calls
        affected_metrics.add("total_call_minutes")
    if sms is not None:
        minimums["sms"] = sms
        affected_metrics.add("sms")

    if re.search(
        r"\b(no|zero|not (?:make|need|use) any) calls?\b"
        r"|\bwill not (?:make|need|use)(?: any)? calls?\b"
        r"|\bdo not (?:plan to )?(?:make|need|use)(?: any)? calls?\b",
        lowered,
    ):
        exact_targets["local_minutes"] = 0
        exact_targets["international_minutes"] = 0
        minimums["local_minutes"] = 0
        minimums["international_minutes"] = 0
        affected_metrics.update(("local_minutes", "international_minutes", "total_call_minutes"))
    elif re.search(r"\bno local calls?\b", lowered):
        exact_targets["local_minutes"] = 0
        minimums["local_minutes"] = 0
        affected_metrics.add("local_minutes")
    elif re.search(r"\bno international calls?\b", lowered):
        exact_targets["international_minutes"] = 0
        minimums["international_minutes"] = 0
        affected_metrics.add("international_minutes")
    if re.search(r"\b(no|zero) data\b|\bwill not (?:need|use)(?: any)? data\b", lowered):
        exact_targets["data_gb"] = 0
        minimums["data_gb"] = 0
        affected_metrics.add("data_gb")
    if re.search(r"\b(no|zero) (?:sms|texts?)\b", lowered):
        exact_targets["sms"] = 0
        minimums["sms"] = 0
        affected_metrics.add("sms")

    totals = _current_totals(current_recommendation)
    if re.search(r"\bmore data\b|\bheavier data\b|\bheavy data\b", lowered):
        comparative.append("more_data")
        affected_metrics.add("data_gb")
        if totals.get("total_data_gb") is not None:
            minimums["data_gb"] = max(
                minimums.get("data_gb", 0), float(totals["total_data_gb"]) * 1.25
            )
    if re.search(r"\b(less|lower|reduce|fewer) data\b", lowered):
        comparative.append("less_data")
        affected_metrics.add("data_gb")
    if re.search(r"\bmore international (?:calls?|minutes?)\b", lowered):
        comparative.append("more_international")
        affected_metrics.add("international_minutes")
        if totals.get("total_international_minutes") is not None:
            minimums["international_minutes"] = max(
                minimums.get("international_minutes", 0),
                float(totals["total_international_minutes"]) * 1.25,
            )
    if re.search(r"\bmore (?:calls?|call minutes?|voice)\b", lowered):
        comparative.append("more_calls")
        affected_metrics.update(("local_minutes", "international_minutes", "total_call_minutes"))
        if totals.get("total_local_minutes") is not None:
            minimums["local_minutes"] = max(
                minimums.get("local_minutes", 0),
                float(totals["total_local_minutes"]) * 1.25,
            )
        if totals.get("total_international_minutes") is not None:
            minimums["international_minutes"] = max(
                minimums.get("international_minutes", 0),
                float(totals["total_international_minutes"]) * 1.25,
            )
    if re.search(r"\b(fewer|less|lower|reduce) (?:calls?|call minutes?|voice)\b", lowered):
        comparative.append("fewer_calls")
        affected_metrics.update(("local_minutes", "international_minutes", "total_call_minutes"))
    if re.search(r"\bcheaper\b|\blower (?:price|cost)\b|\bspend less\b", lowered):
        comparative.append("cheaper")
    if re.search(r"\bfewer activations?\b|\bless activations?\b", lowered):
        comparative.append("fewer_activations")
    if re.search(r"\blonger validity\b|\bmore validity\b", lowered):
        comparative.append("longer_validity")
        if totals.get("total_validity_days") is not None:
            minimum_validity = max(
                minimum_validity or 0,
                float(totals["total_validity_days"]) + 1,
            )

    restore_original = bool(re.search(r"\brestore (?:my )?original recommendation\b", lowered))
    segments = parse_temporal_segments(text, trip_days) if trip_days else []
    interpretation_parts = []
    if minimums:
        interpretation_parts.append(
            "minimums: "
            + ", ".join(f"{key}={value:g}" for key, value in sorted(minimums.items()))
        )
    if exact_targets:
        interpretation_parts.append(
            "targets: "
            + ", ".join(f"{key}={value:g}" for key, value in sorted(exact_targets.items()))
        )
    if comparative:
        interpretation_parts.append("preferences: " + ", ".join(comparative))
    if segments:
        interpretation_parts.append("separate trip periods requested")

    return {
        "latest_message": text,
        "minimums": minimums,
        "exact_targets": exact_targets,
        "maximum_price_aed": maximum_price,
        "minimum_validity_days": int(math.ceil(minimum_validity)) if minimum_validity else None,
        "comparative": comparative,
        "segments": segments,
        "restore_original": restore_original,
        "interpretation": "; ".join(interpretation_parts) or "No explicit numeric constraint detected.",
        "affected_metrics": sorted(affected_metrics),
        "maximum_price_mentioned": maximum_price is not None,
        "minimum_validity_mentioned": minimum_validity is not None,
        "segments_mentioned": bool(segments),
    }


def merge_requirement_state(previous, latest):
    """Merge active constraints while giving the newest message absolute priority."""

    if latest.get("restore_original"):
        return parse_user_requirements("")

    previous = deepcopy(previous or {})
    merged = deepcopy(latest)
    affected = set(latest.get("affected_metrics", []))
    merged_minimums = dict(previous.get("minimums", {}))
    merged_targets = dict(previous.get("exact_targets", {}))

    for metric in affected:
        merged_minimums.pop(metric, None)
        merged_targets.pop(metric, None)
    merged_minimums.update(latest.get("minimums", {}))
    merged_targets.update(latest.get("exact_targets", {}))
    merged["minimums"] = merged_minimums
    merged["exact_targets"] = merged_targets

    if not latest.get("maximum_price_mentioned"):
        merged["maximum_price_aed"] = previous.get("maximum_price_aed")
    if not latest.get("minimum_validity_mentioned"):
        merged["minimum_validity_days"] = previous.get("minimum_validity_days")
    if not latest.get("segments_mentioned"):
        merged["segments"] = deepcopy(previous.get("segments", []))

    # Comparatives are evaluated once against the current validated plan. Any
    # hard minimum they create is retained above for subsequent refinements.
    merged["comparative"] = list(latest.get("comparative", []))
    merged["active"] = bool(
        merged_minimums
        or merged_targets
        or merged.get("maximum_price_aed") is not None
        or merged.get("minimum_validity_days") is not None
        or merged.get("segments")
    )
    return merged


def parse_temporal_segments(message, trip_days):
    lowered = message.lower()
    descriptors = []

    def add(start, end, interpretation, **modifiers):
        start = max(1, start)
        end = min(trip_days, end)
        if start <= end:
            descriptors.append(
                {
                    "start_day": start,
                    "end_day": end,
                    "usage_interpretation": interpretation,
                    "modifiers": modifiers,
                }
            )

    first_week = "first week" in lowered or "first seven days" in lowered
    second_week = "second week" in lowered or "next week" in lowered
    final_three = "final three days" in lowered or "last three days" in lowered
    first_half = "first half" in lowered
    second_half = "second half" in lowered or "final half" in lowered
    calls_only_final = final_three and "only need calls" in lowered
    calls_only_first_half = first_half and "only need calls" in lowered

    if calls_only_final and trip_days > 3:
        add(
            1,
            trip_days - 3,
            "Usual data use without calls",
            data_factor=1.0,
            local_factor=0.0,
            international_factor=0.0,
            sms_factor=1.0,
        )

    if first_week:
        first_text = lowered.split("second week")[0].split("next week")[0]
        wifi = "wi-fi" in first_text or "wifi" in first_text
        light = wifi or "light" in first_text or "not need much data" in first_text
        no_calls = "no calls" in first_text
        add(
            1,
            7,
            "Wi-Fi available with light data use" if wifi else "Light first-week usage",
            data_factor=0.25 if light else 1.0,
            local_factor=0.0 if no_calls else 1.0,
            international_factor=0.0 if no_calls else 1.0,
            sms_factor=1.0,
        )
    if second_week:
        heavy = any(term in lowered for term in ("heavy data", "much more data", "stream"))
        add(
            8,
            14,
            "Higher data use during the second week" if heavy else "Second-week usage",
            data_factor=3.5 if heavy else 1.0,
            local_factor=1.0,
            international_factor=1.0,
            sms_factor=1.0,
        )
    if final_three:
        only_calls = calls_only_final or "for business calls" in lowered
        add(
            trip_days - 2,
            trip_days,
            "Voice-focused final three days" if only_calls else "Final three-day requirements",
            data_factor=0.15 if only_calls else 1.0,
            local_factor=1.5 if only_calls else 1.0,
            international_factor=1.5 if only_calls else 1.0,
            sms_factor=1.0,
        )
    if first_half and not first_week:
        midpoint = math.ceil(trip_days / 2)
        add(
            1,
            midpoint,
            "First-half trip requirements",
            data_factor=0.5 if ("wi-fi" in lowered or "wifi" in lowered or "light" in lowered) else 1.0,
            local_factor=1.0,
            international_factor=1.0,
            sms_factor=1.0,
        )
        if calls_only_first_half and midpoint < trip_days:
            add(
                midpoint + 1,
                trip_days,
                "Usual data use without calls",
                data_factor=1.0,
                local_factor=0.0,
                international_factor=0.0,
                sms_factor=1.0,
            )
    if second_half and not second_week:
        midpoint = math.ceil(trip_days / 2)
        add(
            midpoint + 1,
            trip_days,
            "Higher second-half usage" if "heavy" in lowered or "stream" in lowered else "Second-half trip requirements",
            data_factor=3.5 if "heavy" in lowered or "stream" in lowered else 1.0,
            local_factor=1.0,
            international_factor=1.0,
            sms_factor=1.0,
        )

    if not descriptors:
        return []

    descriptors.sort(key=lambda item: item["start_day"])
    completed = []
    cursor = 1
    for descriptor in descriptors:
        if descriptor["start_day"] > cursor:
            add_end = descriptor["start_day"] - 1
            completed.append(
                {
                    "start_day": cursor,
                    "end_day": add_end,
                    "usage_interpretation": "Usual trip usage",
                    "modifiers": {
                        "data_factor": 1.0,
                        "local_factor": 1.0,
                        "international_factor": 1.0,
                        "sms_factor": 1.0,
                    },
                }
            )
        if descriptor["start_day"] < cursor:
            descriptor = {**descriptor, "start_day": cursor}
        if descriptor["start_day"] <= descriptor["end_day"]:
            completed.append(descriptor)
            cursor = descriptor["end_day"] + 1
    if cursor <= trip_days:
        completed.append(
            {
                "start_day": cursor,
                "end_day": trip_days,
                "usage_interpretation": "Usual trip usage",
                "modifiers": {
                    "data_factor": 1.0,
                    "local_factor": 1.0,
                    "international_factor": 1.0,
                    "sms_factor": 1.0,
                },
            }
        )
    for index, segment in enumerate(completed, start=1):
        segment["segment_id"] = f"segment-{index}"
    return completed
