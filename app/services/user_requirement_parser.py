"""Deterministic extraction of explicit roaming-plan requirements."""

import math
import re
from copy import deepcopy


def _number(pattern, text):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _current_totals(current_recommendation):
    return (current_recommendation or {}).get("selection", {})


def _strictly_more(value, metric):
    increment = 0.001 if metric == "data_gb" else 1
    return float(value) + increment


def _active_minimums(current_recommendation):
    return (
        (current_recommendation or {})
        .get("_active_requirements", {})
        .get("minimums", {})
    )


def _mentions_whole_trip(text):
    return bool(
        re.search(
            r"\b(?:across|throughout|for)\s+(?:all\s+|the\s+)?"
            r"(?:entire\s+|whole\s+)?(?:(?:\d+|three|seven|fourteen)\s+days?|trip)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _numeric_segment_requirements(text):
    """Extract only service quantities from one time-bounded clause."""

    patterns = {
        "data_gb": r"(\d+(?:\.\d+)?)\s*gb\b",
        "local_minutes": r"(\d+(?:\.\d+)?)\s+local(?:\s+call)?\s+minutes?\b",
        "international_minutes": (
            r"(\d+(?:\.\d+)?)\s+international(?:\s+call)?\s+minutes?\b"
        ),
        "sms": r"(\d+(?:\.\d+)?)\s*(?:sms|texts?)\b",
    }
    return {
        metric: value
        for metric, pattern in patterns.items()
        if (value := _number(pattern, text)) is not None
    }


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
    if maximum_price is None:
        maximum_price = _number(
            r"\bbudget(?:\s+(?:is|of|around|about|like))?\s*"
            r"(?:is\s+|of\s+|around\s+|about\s+|like\s+)?"
            r"(?:aed\s*)?(\d+(?:\.\d+)?)\s*(?:aed|dhs?|dirhams?)?\b",
            text,
        )
    if maximum_price is None:
        maximum_price = _number(
            r"\b(?:aed\s*)?(\d+(?:\.\d+)?)\s*(?:aed|dhs?|dirhams?)?"
            r"\s+(?:as\s+my\s+|for\s+the\s+)?budget\b",
            text,
        )
    if maximum_price is not None:
        comparative.append("budget_limited")
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

    # A short correction such as "no, 200 across the 3 days" inherits the
    # single active metric instead of losing the already-established unit.
    if not minimums:
        scoped_number = _number(
            r"\b(\d+(?:\.\d+)?)\s+(?:across|throughout|for)\b",
            text,
        )
        active_minimums = _active_minimums(current_recommendation)
        active_metrics = [
            metric
            for metric in (
                "data_gb",
                "local_minutes",
                "international_minutes",
                "sms",
                "total_call_minutes",
            )
            if metric in active_minimums
        ]
        if scoped_number is not None and len(active_metrics) == 1:
            minimums[active_metrics[0]] = scoped_number
            affected_metrics.add(active_metrics[0])

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
                minimums.get("data_gb", 0),
                _strictly_more(totals["total_data_gb"], "data_gb"),
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
                _strictly_more(
                    totals["total_international_minutes"],
                    "international_minutes",
                ),
            )
    if re.search(r"\bmore local (?:calls?|minutes?)\b", lowered):
        comparative.append("more_local")
        affected_metrics.add("local_minutes")
        if totals.get("total_local_minutes") is not None:
            minimums["local_minutes"] = max(
                minimums.get("local_minutes", 0),
                _strictly_more(
                    totals["total_local_minutes"],
                    "local_minutes",
                ),
            )
    if re.search(r"\bmore (?:calls?|call minutes?|voice)\b", lowered):
        comparative.append("more_calls")
        affected_metrics.update(("local_minutes", "international_minutes", "total_call_minutes"))
        if totals.get("total_local_minutes") is not None:
            minimums["local_minutes"] = max(
                minimums.get("local_minutes", 0),
                _strictly_more(
                    totals["total_local_minutes"],
                    "local_minutes",
                ),
            )
        if totals.get("total_international_minutes") is not None:
            minimums["international_minutes"] = max(
                minimums.get("international_minutes", 0),
                _strictly_more(
                    totals["total_international_minutes"],
                    "international_minutes",
                ),
            )
    if re.search(r"\b(fewer|less|lower|reduce) (?:calls?|call minutes?|voice)\b", lowered):
        comparative.append("fewer_calls")
        affected_metrics.update(("local_minutes", "international_minutes", "total_call_minutes"))
    if re.search(
        r"\bcheap(?:er)?\b|\blower (?:price|cost)\b|\bspend less\b|\bgo low[- ]cost\b",
        lowered,
    ):
        comparative.append("cheaper")
    if re.search(
        r"\b(?:focus|focused|prioriti[sz]e|priority)\b[^.?!]{0,24}\b(?:calls?|voice)\b"
        r"|\b(?:calls?|voice)\b[^.?!]{0,18}\b(?:focus|priority|matters? most)\b",
        lowered,
    ):
        comparative.append("focus_calls")
        affected_metrics.update(
            ("local_minutes", "international_minutes", "total_call_minutes")
        )
    if re.search(
        r"\b(?:focus|focused|prioriti[sz]e|priority)\b[^.?!]{0,24}\bdata\b"
        r"|\bdata\b[^.?!]{0,18}\b(?:focus|priority|matters? most)\b",
        lowered,
    ):
        comparative.append("focus_data")
        affected_metrics.add("data_gb")
    if re.search(
        r"\b(?:focus|focused|prioriti[sz]e|priority)\b[^.?!]{0,24}\b(?:sms|texts?)\b"
        r"|\b(?:sms|texts?)\b[^.?!]{0,18}\b(?:focus|priority|matters? most)\b",
        lowered,
    ):
        comparative.append("focus_sms")
        affected_metrics.add("sms")
    if re.search(r"\bfewer activations?\b|\bless activations?\b", lowered):
        comparative.append("fewer_activations")
    if re.search(r"\blonger validity\b|\bmore validity\b", lowered):
        comparative.append("longer_validity")
        if totals.get("total_validity_days") is not None:
            minimum_validity = max(
                minimum_validity or 0,
                float(totals["total_validity_days"]) + 1,
            )

    reset_constraints = bool(
        re.search(
            r"\bnever\s*mind\b|\bforget (?:that|it|the previous request)\b"
            r"|\b(?:ignore|disregard) (?:that|my previous request|the previous request)\b"
            r"|\bstart (?:again|over|fresh)\b",
            lowered,
        )
    )
    restore_original = bool(
        re.search(
            r"\brestore (?:my |the )?original (?:recommendation|plan|package)\b"
            r"|\b(?:original|initial|first) (?:recommendation|plan|package)\b"
            r"|\b(?:plan|package|recommendation) you (?:first|originally) recommended\b",
            lowered,
        )
    )
    whole_trip_mentioned = _mentions_whole_trip(text)
    segments = parse_temporal_segments(text, trip_days) if trip_days else []
    if whole_trip_mentioned:
        segments = []
    segment_explicit_metrics = {
        metric
        for segment in segments
        for metric in segment.get("explicit_requirements", {})
    }
    for metric in segment_explicit_metrics:
        # A value tied to one named period is not a whole-trip minimum.
        minimums.pop(metric, None)
        exact_targets.pop(metric, None)
    trip_wide_metrics = sorted(
        metric for metric in affected_metrics if metric in minimums and not segments
    )
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
        "minimum_validity_days": math.ceil(minimum_validity) if minimum_validity else None,
        "comparative": comparative,
        "segments": segments,
        "restore_original": restore_original,
        "reset_constraints": reset_constraints,
        "interpretation": "; ".join(interpretation_parts) or "No explicit numeric constraint detected.",
        "affected_metrics": sorted(affected_metrics),
        "trip_wide_metrics": trip_wide_metrics,
        "maximum_price_mentioned": maximum_price is not None,
        "minimum_validity_mentioned": minimum_validity is not None,
        "segments_mentioned": bool(segments),
        "whole_trip_mentioned": whole_trip_mentioned,
    }


def merge_requirement_state(previous, latest):
    """Merge active constraints while giving the newest message absolute priority."""

    if latest.get("restore_original"):
        return parse_user_requirements("")

    previous = {} if latest.get("reset_constraints") else deepcopy(previous or {})
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

    merged_trip_wide = set(previous.get("trip_wide_metrics", []))
    merged_trip_wide.difference_update(affected)
    merged_trip_wide.update(latest.get("trip_wide_metrics", []))
    merged["trip_wide_metrics"] = sorted(merged_trip_wide)

    if not latest.get("maximum_price_mentioned"):
        merged["maximum_price_aed"] = previous.get("maximum_price_aed")
    if not latest.get("minimum_validity_mentioned"):
        merged["minimum_validity_days"] = previous.get("minimum_validity_days")
    if latest.get("whole_trip_mentioned"):
        merged["segments"] = []
    elif not latest.get("segments_mentioned"):
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

    def add(start, end, interpretation, explicit_requirements=None, **modifiers):
        start = max(1, start)
        end = min(trip_days, end)
        if start <= end:
            descriptor = {
                "start_day": start,
                "end_day": end,
                "usage_interpretation": interpretation,
                "modifiers": modifiers,
            }
            if explicit_requirements:
                descriptor["explicit_requirements"] = explicit_requirements
            descriptors.append(descriptor)

    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "fourteen": 14,
    }
    value_before_period_pattern = re.compile(
        r"\b(?P<value>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>gb|local(?:\s+call)?\s+minutes?|"
        r"international(?:\s+call)?\s+minutes?|sms|texts?)\b"
        r"(?:\s+combined)?\s+(?:on|for|during|across)\s+"
        r"(?:day\s+(?P<single_day>\d+)"
        r"|days\s+(?P<start_day>\d+)\s*"
        r"(?:-|\u2013|\u2014|to|through|and)\s*(?P<end_day>\d+))\b",
        flags=re.IGNORECASE,
    )
    for match in value_before_period_pattern.finditer(lowered):
        start_day = int(match.group("single_day") or match.group("start_day"))
        end_day = int(match.group("single_day") or match.group("end_day"))
        if start_day < 1 or end_day > trip_days or start_day > end_day:
            raise ValueError("Split periods must stay within the trip dates.")
        unit = match.group("unit").lower()
        metric = (
            "data_gb"
            if unit == "gb"
            else "local_minutes"
            if unit.startswith("local")
            else "international_minutes"
            if unit.startswith("international")
            else "sms"
        )
        add(
            start_day,
            end_day,
            "Explicit numeric requirements for this trip period",
            explicit_requirements={metric: float(match.group("value"))},
            data_factor=1.0,
            local_factor=1.0,
            international_factor=1.0,
            sms_factor=1.0,
        )

    explicit_period_pattern = re.compile(
        r"\b(?:"
        r"(?P<position>first|final|last)\s+"
        r"(?P<length>\d+|one|two|three|four|five|six|seven|eight|nine|ten|fourteen)\s+days?"
        r"|days\s+(?P<range_start>\d+)\s*"
        r"(?:-|\u2013|\u2014|to|through|and)\s*(?P<range_end>\d+)"
        r"|day\s+(?P<single>\d+)"
        r")\b",
        flags=re.IGNORECASE,
    )
    explicit_matches = (
        [] if descriptors else list(explicit_period_pattern.finditer(lowered))
    )
    for index, match in enumerate(explicit_matches):
        clause_end = (
            explicit_matches[index + 1].start()
            if index + 1 < len(explicit_matches)
            else len(lowered)
        )
        clause = lowered[match.start() : clause_end]
        explicit_requirements = _numeric_segment_requirements(clause)
        if not explicit_requirements:
            continue
        if match.group("range_start") is not None:
            start_day = int(match.group("range_start"))
            end_day = int(match.group("range_end"))
        elif match.group("single") is not None:
            start_day = end_day = int(match.group("single"))
        else:
            length_text = match.group("length")
            length = int(length_text) if length_text.isdigit() else number_words[length_text]
            if match.group("position") == "first":
                start_day, end_day = 1, length
            else:
                start_day, end_day = trip_days - length + 1, trip_days
        if start_day < 1 or end_day > trip_days or start_day > end_day:
            raise ValueError("Split periods must stay within the trip dates.")
        add(
            start_day,
            end_day,
            "Explicit numeric requirements for this trip period",
            explicit_requirements=explicit_requirements,
            data_factor=1.0,
            local_factor=1.0,
            international_factor=1.0,
            sms_factor=1.0,
        )

    explicit_ranges = bool(descriptors)

    first_week = "first week" in lowered or "first seven days" in lowered
    second_week = "second week" in lowered or "next week" in lowered
    final_three = "final three days" in lowered or "last three days" in lowered
    first_half = "first half" in lowered
    second_half = "second half" in lowered or "final half" in lowered
    calls_only_final = final_three and "only need calls" in lowered
    calls_only_first_half = first_half and "only need calls" in lowered

    if not explicit_ranges and calls_only_final and trip_days > 3:
        add(
            1,
            trip_days - 3,
            "Usual data use without calls",
            data_factor=1.0,
            local_factor=0.0,
            international_factor=0.0,
            sms_factor=1.0,
        )

    if not explicit_ranges and first_week:
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
    if not explicit_ranges and second_week:
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
    if not explicit_ranges and final_three:
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
    if not explicit_ranges and first_half and not first_week:
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
    if not explicit_ranges and second_half and not second_week:
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
            if explicit_ranges:
                raise ValueError("Split periods cannot overlap.")
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
