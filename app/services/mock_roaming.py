def recommend_package(packages, destination, duration, requirements, rejected_ids=None):
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

