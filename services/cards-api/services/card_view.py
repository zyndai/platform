"""Canonical public CardView: identity + approved memory facts + provenance.

Agent-facing surfaces (search, data.json, chat, /view) should read this object
so they cannot disagree after a memory approve/revoke.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import config
from models.card import AgentProfileCard

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


def shape_fact(fact: dict) -> dict[str, Any]:
    return {
        "text": fact_object(fact),
        "type": fact_predicate(fact),
        "source": str(fact.get("source") or ""),
        "approved_at": fact.get("approved_at"),
        "expires_at": expires_at(fact),
        "confidence": fact.get("confidence"),
    }


def cite_as(handle: str) -> str:
    base = (config.SITE_BASE_URL or "https://zynd.ai").rstrip("/")
    return f"{base}/p/{handle}" if handle else base


def build_card_view(card: AgentProfileCard, *, claimed: bool) -> dict[str, Any]:
    facts = [shape_fact(f) for f in live_facts(card.zynd_memory)]
    identity = card.identity.model_dump(mode="json")
    view: dict[str, Any] = {
        "handle": card.handle,
        "claimed": claimed,
        "identity": identity,
        "summary": card.summary,
        "skills": [s.model_dump(mode="json") for s in card.skills],
        "projects": [p.model_dump(mode="json") for p in card.projects],
        "working_on": list(card.working_on),
        "can_help_with": list(card.can_help_with),
        "love_talking_about": list(card.love_talking_about),
        "availability": card.availability,
        "facts": facts,
        "cite_as": cite_as(card.handle),
        "fresh_as_of": card.updated_at,
    }
    if claimed:
        view["calendly_url"] = card.calendly_url
        view["google_calendar_url"] = card.google_calendar_url
        view["links"] = identity.get("links") or {}
    else:
        view["calendly_url"] = None
        view["google_calendar_url"] = None
        view["links"] = {}
    return view
