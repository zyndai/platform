"""A3 — saved searches: "tell me when a matching Card is published or updated".

A person saves the filters of a people search. A scheduled job (POST /internal/saved-searches/run)
re-runs every active search, and each STRONG match that has not been reported before becomes a
nudge on the owner's Cards home (and in their nudge email if they opted in). What was already a
match when the search was saved is not reported: only new people are news.

Behind FEATURE_NETWORK_CONTROLS.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from services import match_prefs, network, search as search_service, trust

logger = logging.getLogger(__name__)

MAX_PER_USER = 10
STRONG_MATCH = 0.5
MAX_NOTIFY_PER_SEARCH = 3
MAX_SEEN = 200
RUN_BATCH = 500


def search_key(q: str, role: str, location: str, skills: str) -> str:
    norm = "|".join(" ".join((part or "").lower().split()) for part in (q, role, location, skills))
    return hashlib.sha256(norm.encode()).hexdigest()[:32]


def _strong(q: str, role: str, location: str, skills: str, own_handle: str, hidden: set[str]) -> list[dict]:
    found = search_service.search_agents(q=q, role=role, location=location, skills=skills, limit=20, include_unclaimed=False)
    return [r for r in found if r.get("handle") and r["match_score"] >= STRONG_MATCH
            and r["handle"] != own_handle and r["handle"].lower() not in hidden]


def add(user_id: str, *, q: str = "", role: str = "", location: str = "", skills: str = "", label: str = "") -> dict:
    trust.require_enabled()
    q, role, location, skills = (" ".join((v or "").split())[:200] for v in (q, role, location, skills))
    if not (q or role or skills):
        raise HTTPException(422, "A saved search needs a description, a role or skills")
    mine = network._card_for_user(user_id)       # notifications land on the owner's Card
    key = search_key(q, role, location, skills)
    sb = network._sb().table("saved_searches")
    existing = sb.select("*").eq("user_id", user_id).eq("search_key", key).limit(1).execute().data or []
    if existing:
        if not existing[0]["active"]:
            network._sb().table("saved_searches").update({"active": True}).eq("id", existing[0]["id"]).execute()
        return {"search": public(existing[0]), "created": False}
    count = network._sb().table("saved_searches").select("id", count="exact").eq("user_id", user_id).eq("active", True).execute()
    if (count.count or 0) >= MAX_PER_USER:
        raise HTTPException(409, f"At most {MAX_PER_USER} saved searches")
    hidden = set(match_prefs.get(user_id)["hide_person"])
    seen = [r["handle"] for r in _strong(q, role, location, skills, mine["handle"], hidden)][:MAX_SEEN]
    row = network._sb().table("saved_searches").insert({
        "user_id": user_id, "search_key": key, "label": " ".join((label or q or role or skills).split())[:80],
        "q": q, "role": role, "location": location, "skills": skills, "seen_handles": seen,
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }).execute().data[0]
    return {"search": public(row), "created": True, "already_matching": len(seen)}


def public(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "label", "q", "role", "location", "skills", "active", "created_at", "last_notified_at")}


def list_searches(user_id: str) -> dict:
    trust.require_enabled()
    rows = (network._sb().table("saved_searches").select("*").eq("user_id", user_id)
            .eq("active", True).order("created_at", desc=True).execute().data or [])
    return {"searches": [public(r) for r in rows]}


def remove(user_id: str, search_id: str) -> dict:
    trust.require_enabled()
    done = (network._sb().table("saved_searches").update({"active": False}).eq("id", search_id)
            .eq("user_id", user_id).eq("active", True).execute().data or [])
    if not done:
        raise HTTPException(404, "No such saved search")
    return {"removed": True, "id": search_id}


def run_all() -> dict:
    """Re-run every active search and nudge owners about new strong matches. Never raises for one
    bad search: the others still run."""
    stats = {"searches": 0, "notified": 0, "nudges": 0, "failed": 0}
    if not trust.enabled():
        return {**stats, "enabled": False}
    rows = (network._sb().table("saved_searches").select("*").eq("active", True)
            .order("last_checked_at").limit(RUN_BATCH).execute().data or [])
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        stats["searches"] += 1
        try:
            mine = network._card_for_user(row["user_id"])
            hidden = set(match_prefs.get(row["user_id"])["hide_person"])
            seen = list(row.get("seen_handles") or [])
            fresh = [r for r in _strong(row["q"], row["role"], row["location"], row["skills"], mine["handle"], hidden)
                     if r["handle"] not in seen]
            update: dict = {"last_checked_at": now}
            if fresh:
                shown = fresh[:MAX_NOTIFY_PER_SEARCH]
                network._sb().table("card_nudges").upsert([{
                    "owner_email": (mine.get("owner_email") or "").lower(), "handle": mine["handle"],
                    "dedupe_key": f"search:{row['id']}:{r['handle']}", "kind": "saved_search",
                    "title": f"New match for “{row['label']}”: {r['name'] or r['handle']}",
                    "href": f"/p/{r['handle']}",
                } for r in shown], on_conflict="owner_email,dedupe_key", ignore_duplicates=True).execute()
                update.update(seen_handles=(seen + [r["handle"] for r in fresh])[-MAX_SEEN:], last_notified_at=now)
                stats["notified"] += 1
                stats["nudges"] += len(shown)
            network._sb().table("saved_searches").update(update).eq("id", row["id"]).execute()
        except Exception:  # noqa: BLE001
            logger.exception("saved search %s failed", row.get("id"))
            stats["failed"] += 1
    return {**stats, "enabled": True}
