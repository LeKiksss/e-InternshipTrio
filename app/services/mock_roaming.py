from datetime import date, datetime


MONTHLY_USAGE = {
    "data_gb": 24,
    "local_minutes": 480,
    "international_minutes": 180,
    "sms": 60,
}
RECOMMENDER_NAME = "Roam Like Home"


def calculate_trip_days(start_date, end_date, today=None):
    """Return an inclusive trip duration after validating an ISO date range."""
    try:
        start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    except (TypeError, ValueError) as error:
        raise ValueError("Choose valid departure and return dates.") from error
    if not isinstance(start, date) or not isinstance(end, date):
        raise ValueError("Choose valid departure and return dates.")
    if today and start < today:
        raise ValueError("Choose travel dates in the future.")
    if end < start:
        raise ValueError("Return date must be on or after the departure date.")
    return (end - start).days + 1


def scale_usage(trip_days, baseline=None):
    if not isinstance(trip_days, int) or trip_days < 1:
        raise ValueError("Trip duration must be at least one day.")
    usage = baseline or MONTHLY_USAGE
    factor = trip_days / 30
    return {
        "trip_days": trip_days,
        "data_gb": round(usage["data_gb"] * factor, 1),
        "local_minutes": round(usage["local_minutes"] * factor),
        "international_minutes": round(usage["international_minutes"] * factor),
        "sms": round(usage["sms"] * factor),
    }


def _validity_tier(trip_days):
    for days in (10, 14, 21, 30):
        if trip_days <= days:
            return days
    return trip_days


def _allowances_for_validity(validity):
    factor = max(1, validity / 10)
    return {
        "data_gb": round(10 * factor),
        "local_minutes": round(200 * factor),
        "international_minutes": round(100 * factor),
        "sms": round(50 * factor),
    }


def current_usage_package(destination, trip_days):
    validity = _validity_tier(trip_days)
    allowances = _allowances_for_validity(validity)
    price = round(220 * max(1, validity / 10))
    package_name = "Travel Connect" if validity <= 10 else "Global Explorer" if validity <= 14 else "Global Explorer Extended"
    return {
        "id": f"travel-connect-{validity}",
        "recommendation_name": RECOMMENDER_NAME,
        "name": package_name,
        "destination": destination,
        "price": price,
        "currency": "AED",
        "validity_days": validity,
        "data_gb": allowances["data_gb"],
        "data_allowance": f"{allowances['data_gb']} GB",
        "local_minutes": allowances["local_minutes"],
        "voice_minutes": allowances["local_minutes"],
        "international_minutes": allowances["international_minutes"],
        "sms_allowance": allowances["sms"],
        "preferred_network": "Preferred Partner 1",
        "activation_code": "*170*201#",
        "activation_instructions": "Review the activation code and confirmation screen before continuing. No package is activated automatically.",
        "why": f"Based on your recent usage, {package_name} is the closest match for your {trip_days}-day trip.",
        "change_summary": "Initial recommendation based on current usage.",
        "prototype": True,
        "updated_at": datetime.now().strftime("%d %b %Y"),
    }


ADJUSTMENT_KEYWORDS = (
    ("cheaper", ("cheap", "cheaper", "less expensive", "lower price", "too expensive")),
    ("more_data", ("more data", "heavy data", "streaming", "video", "hotspot")),
    ("less_data", ("less data", "do not need much data", "mostly messaging")),
    ("more_international", ("international calls", "international minutes", "call home", "overseas calls")),
    ("more_calls", ("more calls", "more call minutes", "more minutes", "voice", "calling")),
    ("fewer_calls", ("fewer calls", "less voice", "no calls", "do not call")),
    ("longer", ("longer trip", "longer validity", "more days")),
    ("keep", ("keep this", "keep the recommendation", "looks good", "use this plan")),
)


def parse_adjustment(text):
    normalized = " ".join((text or "").lower().split())
    if not normalized:
        return None
    for intent, phrases in ADJUSTMENT_KEYWORDS:
        if any(phrase in normalized for phrase in phrases):
            return intent
    return None


def adjusted_package(intent, destination, trip_days):
    base = current_usage_package(destination, trip_days)
    validity = base["validity_days"]
    if intent == "keep":
        base["change_summary"] = "The original current-usage recommendation was restored."
        return base

    variants = {
        "cheaper": {
            "id": f"travel-data-lite-{validity}", "name": "Travel Data Lite",
            "price": round(base["price"] * 0.72), "data_gb": max(4, round(base["data_gb"] * 0.55)),
            "local_minutes": max(60, round(base["local_minutes"] * 0.45)),
            "international_minutes": max(20, round(base["international_minutes"] * 0.35)),
            "sms_allowance": max(20, round(base["sms_allowance"] * 0.5)),
            "change_summary": "Reduced the price by lowering the included data and call allowances.",
        },
        "less_data": {
            "id": f"travel-data-lite-{validity}", "name": "Travel Data Lite",
            "price": round(base["price"] * 0.78), "data_gb": max(4, round(base["data_gb"] * 0.5)),
            "local_minutes": base["local_minutes"], "international_minutes": base["international_minutes"],
            "sms_allowance": base["sms_allowance"],
            "change_summary": "Reduced the data allowance for a lighter, messaging-focused trip.",
        },
        "more_data": {
            "id": f"data-max-abroad-{validity}", "name": "Data Max Abroad",
            "price": round(base["price"] * 1.28), "data_gb": round(base["data_gb"] * 2.2),
            "local_minutes": base["local_minutes"], "international_minutes": base["international_minutes"],
            "sms_allowance": base["sms_allowance"],
            "change_summary": "Increased the data allowance for streaming, video, or hotspot use.",
        },
        "more_calls": {
            "id": f"voice-traveller-{validity}", "name": "Voice Traveller",
            "price": round(base["price"] * 1.22), "data_gb": base["data_gb"],
            "local_minutes": round(base["local_minutes"] * 2.5),
            "international_minutes": round(base["international_minutes"] * 1.8),
            "sms_allowance": base["sms_allowance"],
            "change_summary": "Increased local and roaming voice minutes for more frequent calls.",
        },
        "fewer_calls": {
            "id": f"data-max-abroad-{validity}", "name": "Data Max Abroad",
            "price": round(base["price"] * 0.92), "data_gb": round(base["data_gb"] * 1.4),
            "local_minutes": max(20, round(base["local_minutes"] * 0.2)),
            "international_minutes": max(10, round(base["international_minutes"] * 0.15)),
            "sms_allowance": base["sms_allowance"],
            "change_summary": "Shifted value from voice minutes into data for a low-call trip.",
        },
        "more_international": {
            "id": f"voice-traveller-{validity}", "name": "Voice Traveller",
            "price": round(base["price"] * 1.25), "data_gb": base["data_gb"],
            "local_minutes": base["local_minutes"],
            "international_minutes": round(base["international_minutes"] * 3),
            "sms_allowance": base["sms_allowance"],
            "change_summary": "Added more international minutes for calls home and overseas calls.",
        },
        "longer": {
            "id": f"global-explorer-{max(30, trip_days)}", "name": "Global Explorer",
            "price": round(base["price"] * 1.35), "validity_days": max(30, trip_days),
            "data_gb": round(base["data_gb"] * 1.5),
            "local_minutes": round(base["local_minutes"] * 1.5),
            "international_minutes": round(base["international_minutes"] * 1.5),
            "sms_allowance": round(base["sms_allowance"] * 1.5),
            "change_summary": "Extended validity and allowances to provide more flexibility for a longer trip.",
        },
    }
    changes = variants.get(intent)
    if not changes:
        return None
    base.update(changes)
    base["voice_minutes"] = base["local_minutes"]
    base["data_allowance"] = f"{base['data_gb']} GB"
    base["why"] = f"{base['name']} reflects your requested adjustment and covers the selected {trip_days}-day trip."
    base["activation_code"] = {
        "cheaper": "*170*202#", "less_data": "*170*202#", "more_data": "*170*203#",
        "more_calls": "*170*204#", "fewer_calls": "*170*203#",
        "more_international": "*170*204#", "longer": "*170*205#",
    }.get(intent, base["activation_code"])
    return base


def recommend_package(packages, destination, duration, requirements, rejected_ids=None):
    """Retain the original catalogue matcher for existing demo states and compatibility."""
    rejected = set(rejected_ids or [])
    eligible = [p for p in packages if destination in p.destinations and p.id not in rejected]
    if not eligible:
        return None
    words = (requirements or "").lower()
    if any(w in words for w in ("cheap", "lowest", "low price", "expensive")):
        eligible.sort(key=lambda p: p.price)
    elif any(w in words for w in ("call", "voice", "minutes")):
        eligible.sort(key=lambda p: (p.voice_minutes, p.validity_days), reverse=True)
    elif any(w in words for w in ("stream", "video", "heavy data", "more data")):
        eligible.sort(key=lambda p: (float(p.data_allowance.split()[0]), p.validity_days), reverse=True)
    else:
        eligible.sort(key=lambda p: (abs(p.validity_days - duration), p.price))
    return eligible[0]
