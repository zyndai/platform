"""One result shape for people search, whatever source found the person.

    {handle, name, headline, location, why[], sources[], claimed, score,
     next_action: connect | invite_to_claim | view_profile, url, skills[], linkedin_url}

Cards is the one people index. A Zynd user is the same person as their Card (merged by
handle) and an external LinkedIn result is the same person as a Card that links the same
profile (merged by LinkedIn URL). Pure functions: no I/O, so the merge rules are unit-tested.
"""
from __future__ import annotations

from urllib.parse import urlsplit

STRONG_MATCH = 0.5
ZYND_BONUS = 0.1          # also found by profile similarity: more likely the right person
EXTERNAL_BASE = 0.3       # external results rank below any real Card match
EXTERNAL_STEP = 0.01      # but keep the provider's order among themselves
MAX_WHY = 4


def linkedin_key(url: object) -> str:
    """host/path of a LinkedIn profile URL, lowercased, or '' for anything else."""
    if not isinstance(url, str) or "linkedin.com" not in url.lower():
        return ""
    raw = url.strip()
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}" if host.endswith("linkedin.com") and path else ""


def _next_action(handle: str | None, claimed: bool) -> str:
    if handle and claimed:
        return "connect"
    return "view_profile"


def with_invites(people: list[dict], uid: str, enabled: bool) -> list[dict]:
    """Offer an invitation to everyone who has no claimed Card but a LinkedIn profile and a name.

    The ref is signed here so invite_to_claim can trust the name and headline it will publish.
    Off, nobody is offered one and next_action stays view_profile."""
    if not enabled:
        return people
    from app.services import invite_refs
    for person in people:
        if person["claimed"] or not person.get("linkedin_url") or not person.get("name"):
            continue
        ref = invite_refs.sign(
            uid, linkedin_url=person["linkedin_url"], name=person["name"], headline=person.get("headline") or "")
        if ref:
            person["next_action"] = "invite_to_claim"
            person["invite_ref"] = ref
    return people


def _score(value: object) -> float:
    return round(float(value), 3) if isinstance(value, (int, float)) else 0.0


def person_from_card(row: dict) -> dict:
    """A Cards search hit (see people_discovery.search_cards)."""
    handle = row.get("handle") or None
    claimed = row.get("claimed") is True
    return {
        "handle": handle,
        "name": row.get("name") or "",
        "headline": row.get("headline") or "",
        "location": row.get("location") or "",
        "why": list(row.get("why") or [])[:MAX_WHY],
        "sources": ["card"],
        "claimed": claimed,
        "score": _score(row.get("match_score")),
        "next_action": _next_action(handle, claimed),
        "url": row.get("url") or "",
        "skills": list(row.get("skills") or [])[:8],
        "linkedin_url": row.get("linkedin_url") or "",
    }


def person_from_zynd(row: dict, card: dict, card_url: str) -> dict:
    """A Zynd user that matched on profile similarity, identified by their Card."""
    handle = card.get("handle") or None
    return {
        "handle": handle,
        "name": card.get("name") or row.get("display_name") or "",
        "headline": card.get("headline") or "",
        "location": card.get("location") or "",
        "why": [f"Zynd profile · {label}" for label in (row.get("matched_on") or [])[:2]]
               or ["Matches their Zynd profile"],
        "sources": ["zynd"],
        "claimed": card.get("claimed") is True,
        "score": _score(row.get("similarity")),
        "next_action": _next_action(handle, card.get("claimed") is True),
        "url": card_url,
        "skills": [],
        "linkedin_url": "",
    }


def person_from_external(row: dict, index: int) -> dict:
    """An external (LinkedIn) result: no Card yet, so nothing to connect to."""
    title, company = row.get("title") or "", row.get("company") or ""
    headline = f"{title} at {company}" if title and company else (title or company)
    return {
        "handle": None,
        "name": row.get("name") or "",
        "headline": headline,
        "location": "",
        "why": ["Found on LinkedIn" + (f" · {headline}" if headline else "")],
        "sources": ["linkedin"],
        "claimed": False,
        "score": round(max(EXTERNAL_BASE - EXTERNAL_STEP * index, 0.0), 3),
        "next_action": "view_profile",
        "url": row.get("linkedin_url") or "",
        "skills": [],
        "linkedin_url": row.get("linkedin_url") or "",
    }


def _identity_keys(person: dict) -> list[str]:
    keys = []
    if person.get("handle"):
        keys.append(f"handle:{person['handle'].lower()}")
    li = linkedin_key(person.get("linkedin_url"))
    if li:
        keys.append(f"li:{li}")
    return keys


def _absorb(base: dict, other: dict) -> None:
    for source in other["sources"]:
        if source not in base["sources"]:
            base["sources"].append(source)
    for reason in other["why"]:
        if reason not in base["why"]:
            base["why"].append(reason)
    base["why"] = base["why"][:MAX_WHY]
    for field in ("name", "headline", "location", "url", "linkedin_url"):
        if not base.get(field) and other.get(field):
            base[field] = other[field]
    if not base["handle"] and other["handle"]:
        base["handle"], base["claimed"] = other["handle"], other["claimed"]
        base["next_action"] = other["next_action"]
    if other.get("skills") and not base.get("skills"):
        base["skills"] = other["skills"]
    if "zynd" in other["sources"] or "zynd" in base["sources"]:
        base["score"] = round(min(max(base["score"], other["score"]) + ZYND_BONUS, 1.0), 3)
    else:
        base["score"] = max(base["score"], other["score"])


def merge_people(people: list[dict]) -> list[dict]:
    """One entry per person, keyed by Card handle or LinkedIn URL, best score first."""
    merged: list[dict] = []
    by_key: dict[str, dict] = {}
    for person in people:
        keys = _identity_keys(person)
        existing = next((by_key[k] for k in keys if k in by_key), None)
        if existing is None:
            existing = person
            merged.append(person)
        else:
            _absorb(existing, person)
        for key in set(keys) | set(_identity_keys(existing)):
            by_key[key] = existing
    return sorted(merged, key=lambda p: (-p["score"], not p["claimed"], p["name"].lower()))


def strong_count(people: list[dict]) -> int:
    return sum(1 for p in people if p["score"] >= STRONG_MATCH)
