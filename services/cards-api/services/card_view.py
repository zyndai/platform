"""Canonical public CardView: identity + approved memory facts + provenance.

Agent-facing surfaces (search, data.json, chat, /view) should read this object
so they cannot disagree after a memory approve/revoke.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from models.card import AgentProfileCard, CardFact, CardView

HALF_LIFE_DAYS = {
    "is_seeking": 7,
    "is_working_on": 14,
    "is_building": 60,
}


def _parse_ts(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fact_object(fact: dict) -> str:
    if not isinstance(fact, dict):
        return ""
    return str(fact.get("object") or fact.get("value") or "").strip()


def fact_predicate(fact: dict) -> str:
    if not isinstance(fact, dict):
        return ""
    return str(fact.get("predicate") or fact.get("type") or "").strip()


def expires_at(fact: dict) -> str | None:
    days = HALF_LIFE_DAYS.get(fact_predicate(fact))
    if days is None and isinstance(fact, dict) and fact.get("half_life_days") is not None:
        try:
            days = int(fact["half_life_days"])
        except (TypeError, ValueError):
            days = None
    approved = _parse_ts(fact.get("approved_at") if isinstance(fact, dict) else None)
    if not days or not approved:
        return None
    return (approved + timedelta(days=days)).isoformat()


def is_expired(fact: dict, now: datetime | None = None) -> bool:
    stamp = expires_at(fact)
    if not stamp:
        return False
    end = _parse_ts(stamp)
    if not end:
        return False
    now = now or datetime.now(timezone.utc)
    return now >= end


def live_facts(facts: list | None, now: datetime | None = None) -> list[dict]:
    out = []
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        if not fact_object(fact):
            continue
        if is_expired(fact, now):
            continue
        out.append(fact)
    return out


def shape_fact(fact: dict) -> CardFact:
    conf = fact.get("confidence")
    try:
        confidence = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        confidence = None
    raw_approved = fact.get("approved_at")
    if hasattr(raw_approved, "isoformat"):
        approved = raw_approved.isoformat()
    elif isinstance(raw_approved, str):
        approved = raw_approved
    else:
        approved = None
    return CardFact(
        text=fact_object(fact),
        type=fact_predicate(fact),
        source=str(fact.get("source") or ""),
        approved_at=approved,
        expires_at=expires_at(fact),
        confidence=confidence,
    )


def cite_as(handle: str) -> str:
    base = (config.SITE_BASE_URL or "https://zynd.ai").rstrip("/")
    return f"{base}/p/{handle}" if handle else base


def build_card_view(card: AgentProfileCard, *, claimed: bool) -> CardView:
    facts = [shape_fact(f) for f in live_facts(card.zynd_memory)]
    identity = card.identity.model_dump(mode="json")
    view = CardView(
        handle=card.handle,
        claimed=claimed,
        identity=card.identity,
        summary=card.summary,
        skills=list(card.skills),
        projects=list(card.projects),
        working_on=list(card.working_on),
        can_help_with=list(card.can_help_with),
        love_talking_about=list(card.love_talking_about),
        availability=card.availability,
        facts=facts,
        cite_as=cite_as(card.handle),
        fresh_as_of=card.updated_at or None,
        calendly_url=card.calendly_url if claimed else None,
        google_calendar_url=card.google_calendar_url if claimed else None,
        links=(identity.get("links") or {}) if claimed else {},
    )
    return view


def freshness_boost(fact: dict, now: datetime | None = None) -> float:
    """0..0.1 boost for facts that still have most of their half-life left."""
    stamp = expires_at(fact)
    if not stamp:
        return 0.05
    end = _parse_ts(stamp)
    approved = _parse_ts(fact.get("approved_at") if isinstance(fact, dict) else None)
    if not end or not approved:
        return 0.0
    now = now or datetime.now(timezone.utc)
    total = (end - approved).total_seconds()
    remaining = (end - now).total_seconds()
    if total <= 0 or remaining <= 0:
        return 0.0
    return round(0.1 * min(1.0, remaining / total), 4)
