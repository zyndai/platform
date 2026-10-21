"""A8 — match controls: hide a person, mute a topic, "less like this".

Stored per user in cards.match_preferences. hide_person and less_like_this hold a Card handle;
mute_topic a short lowercase phrase. Memory reads them when it searches for the user: hidden
people and muted topics are dropped from the results, and people like a "less like this" Card are
ranked lower (Cards applies that penalty, see search.search_agents).

Behind FEATURE_NETWORK_CONTROLS.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from services import network, trust

KINDS = ("hide_person", "mute_topic", "less_like_this")
MAX_PER_USER = 200


def normalize(kind: str, value: str) -> str:
    if kind not in KINDS:
        raise HTTPException(422, "kind must be one of: " + ", ".join(KINDS))
    text = " ".join((value or "").split())
    if kind == "mute_topic":
        text = re.sub(r"[^\w\s.+#-]", "", text.lower())[:60].strip()
    else:
        text = text.lstrip("@").lower()[:64]
    if not text:
        raise HTTPException(422, "A value is required")
    return text


def add(user_id: str, kind: str, value: str) -> dict:
    trust.require_enabled()
    value = normalize(kind, value)
    if kind != "mute_topic":
        rows = (network._sb().table("agent_profile_cards").select("id").eq("handle", value)
                .eq("status", "published").limit(1).execute().data or [])
        if not rows:
            raise HTTPException(404, "Card not found")
    total = network._sb().table("match_preferences").select("id", count="exact").eq("user_id", user_id).execute()
    if (total.count or 0) >= MAX_PER_USER:
        raise HTTPException(409, f"At most {MAX_PER_USER} match preferences")
    network._sb().table("match_preferences").upsert(
        {"user_id": user_id, "kind": kind, "value": value}, on_conflict="user_id,kind,value", ignore_duplicates=True).execute()
    return {"kind": kind, "value": value}


def remove(user_id: str, kind: str, value: str) -> dict:
    trust.require_enabled()
    value = normalize(kind, value)
    gone = (network._sb().table("match_preferences").delete().eq("user_id", user_id)
            .eq("kind", kind).eq("value", value).execute().data or [])
    if not gone:
        raise HTTPException(404, "No such preference")
    return {"removed": True, "kind": kind, "value": value}


def get(user_id: str) -> dict:
    """{hide_person: [...], mute_topic: [...], less_like_this: [...]}; empty when the feature is off."""
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    if not trust.enabled():
        return out
    rows = (network._sb().table("match_preferences").select("kind,value").eq("user_id", user_id)
            .order("created_at").execute().data or [])
    for r in rows:
        if r["kind"] in out:
            out[r["kind"]].append(r["value"])
    return out
