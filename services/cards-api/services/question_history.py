"""Bounded question text for owner history; never store conversation context."""
import json
import re

_CONTACT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|https?://\S+|"
    r"(?:\+?\d[\s().-]*){10,}|\b[A-Za-z0-9_-]{32,}\b",
    re.IGNORECASE,
)


def stored_question(text: str) -> tuple[str, bool]:
    cleaned = _CONTACT.sub("[redacted]", " ".join(text.split()))
    # The event metadata cap measures JSON with escaped Unicode. Leave room
    # for category/source/length fields so multi-byte input does not drop the event.
    low, high = 0, len(cleaned)
    while low < high:
        mid = (low + high + 1) // 2
        if len(json.dumps(cleaned[:mid]).encode()) <= 1600:
            low = mid
        else:
            high = mid - 1
    return cleaned[:low], low < len(cleaned)
