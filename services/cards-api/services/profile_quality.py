"""Validation for public topics, independent of narrative profile text."""
import re

PLACEHOLDERS = frozenset({"general", "misc", "miscellaneous", "other", "none", "null", "undefined", "unknown", "n/a"})


def clean_topic(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.strip().strip("\"'`").split())
    if text.casefold() in PLACEHOLDERS or not text or len(text) > 100 or len(text.split()) > 8:
        return ""
    if re.search(r"[!?;\n]|\.\s|https?://|\b(?:founder of|founded|organized|worked at)\b", text, re.I):
        return ""
    return text


def clean_topics(values: list) -> list:
    """Keep evidence and other skill fields when filtering a list of skill objects."""
    out, seen = [], set()
    for value in values:
        name = clean_topic(value.get("name") if isinstance(value, dict) else getattr(value, "name", value))
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append({**value, "name": name} if isinstance(value, dict) else value)
    return out
