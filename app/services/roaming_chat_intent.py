"""Deterministic chat intents that should not consume a Gemini request."""

import re

_GREETING = re.compile(
    r"^(?:"
    r"hi+|hello+|hey+|hiya|howdy|greetings|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"morning|afternoon|evening|"
    r"salaam|salam|assalamu\s+alaikum|as-salamu\s+alaikum|"
    r"what(?:'s|\s+is)\s+up|how\s+are\s+you"
    r")(?:\s+(?:there|everyone|team|assistant|bot))?[\s!,.?]*$",
    flags=re.IGNORECASE,
)
_ORIGINAL = re.compile(
    r"(?:"
    r"\b(?:original|initial|first)\s+(?:plan|package|recommendation|one)\b|"
    r"\b(?:plan|package|recommendation)\s+(?:you\s+)?(?:first|originally)\s+recommended\b|"
    r"\b(?:go|come|take|bring|return|switch|revert|restore|get)\b[^.?!]{0,45}"
    r"\b(?:original|initial|first)\b"
    r")",
    flags=re.IGNORECASE,
)
_PREVIOUS = re.compile(
    r"(?:"
    r"\b(?:previous|prior|last)\s+(?:plan|package|recommendation|one)\b|"
    r"\b(?:go|come|take|bring|return|switch|revert|restore|get)\s+back\b[^.?!]{0,35}"
    r"\b(?:plan|package|recommendation|one|previous)\b|"
    r"\bgo\s+back\s+one\b"
    r")",
    flags=re.IGNORECASE,
)


def classify_roaming_chat_intent(message):
    text = " ".join((message or "").strip().split())
    if _GREETING.fullmatch(text):
        lowered = text.lower()
        if "morning" in lowered:
            reply = "Good morning! How can I help with your roaming plan?"
        elif "afternoon" in lowered:
            reply = "Good afternoon! How can I help with your roaming plan?"
        elif "evening" in lowered:
            reply = "Good evening! How can I help with your roaming plan?"
        elif any(word in lowered for word in ("salaam", "salam")):
            reply = "Wa alaikum assalam! How can I help with your roaming plan?"
        else:
            reply = "Hello! How can I help with your roaming plan?"
        return {"kind": "greeting", "reply": reply}
    if _ORIGINAL.search(text):
        return {"kind": "original"}
    if _PREVIOUS.search(text):
        return {"kind": "previous"}
    return {"kind": "refinement"}
