STRONG_RESULT = {
    "download_speed": 184,
    "upload_speed": 32,
    "latency": 18,
    "verdict": "Excellent for video calls, streaming, gaming, and everyday browsing.",
}

WEAK_RESULT = {
    "download_speed": 8.4,
    "upload_speed": 1.8,
    "latency": 126,
    "verdict": "Your connection may struggle with video calls and high-quality streaming.",
}


def result_for_state(state="strong"):
    return dict(WEAK_RESULT if state == "weak" else STRONG_RESULT)

