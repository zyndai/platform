"""S10 owner-only aggregation. Memory is reached exclusively over HTTP."""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import config
from services import cards, events, zynd_mcp, zynd_memory
from services.card_view import expires_at, fact_predicate, _parse_ts
from services.completeness import completeness

DEFAULT_PREFS = {"weekly_digest": True, "email_nudges": False}


def enabled() -> bool:
    return config.FEATURE_S10_HOME and config.SUPABASE_DB_SCHEMA == "cards"


def owner_rows(email: str) -> list[dict]:
    return (config.get_supabase().table("agent_profile_cards").select("*")
            .ilike("owner_email", cards._like_literal(email.strip().lower()))
            .neq("status", "merged").order("created_at", desc=True).execute().data or [])


def current_row(email: str) -> dict | None:
    rows = owner_rows(email)
    return next((r for r in rows if r["status"] == "published"), rows[0] if rows else None)


def card_from_row(row: dict):
    card = cards._row_to_card(row)
    card.status = row["status"]
    card.updated_at = row["updated_at"]
    return card


def activity(handle: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    empty = {"available": False, "views": None, "agent_hits": None,
             "intro_requests": None, "queries": [], "query_capture_available": False}
    if not events.events_enabled():
        return empty
    try:
        sb = config.get_supabase()
        since = (now - timedelta(days=7)).isoformat()
        def count(event: str, actor: str | None = None):
            q = sb.table("card_events").select("id", count="exact", head=True).eq("handle", handle).gte("ts", since).eq("event", event)
            if actor:
                q = q.eq("actor_class", actor)
            return q.execute().count or 0
        queries = query_summaries(sb, handle, since)
        return {**empty, "available": True, "views": count("view", "human"),
                "agent_hits": count("agent_fetch", "ai_agent") + count("view", "ai_agent"),
                "intro_requests": count("intro_request") if config.FEATURE_S12_INTROS else None,
                "queries": queries, "query_capture_available": bool(queries)}
    except Exception:
        # An unavailable event store is not zero traffic.
        return empty


def query_summaries(sb, handle: str, since: str) -> list[dict]:
    """Consume matching queries if S11 emits them; never collect new text here.

    Owner aggregation selects only metadata, never IPs/requester identities.
    Unknown event shapes do not become fabricated questions.
    """
    rows = (sb.table("card_events").select("meta").eq("handle", handle)
            .eq("event", "agent_fetch").eq("actor_class", "ai_agent").gte("ts", since)
            .order("ts", desc=True).limit(1000).execute().data or [])
    counts = Counter()
    for row in rows:
        meta = row.get("meta") or {}
        query = meta.get("query")
        if meta.get("endpoint") != "ask" or not isinstance(query, str) or not query.strip():
            continue
        text = " ".join(query.split())[:160]
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|https?://\S+|\b\d[\d ()+-]{8,}\d\b|\b[A-Za-z0-9_-]{32,}\b", "[redacted]", text)
        counts[text] += 1
    return [{"query": query, "count": count} for query, count in counts.most_common(5)]


def nudge_candidates(card, pending: int | None, now: datetime | None = None, matches: int = 0) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    href = f"/p/{quote(card.handle, safe='')}/edit"
    out = []
    for fact in card.zynd_memory or []:
        end = _parse_ts(expires_at(fact))
        if fact_predicate(fact) != "is_seeking" or not end or not now < end <= now + timedelta(days=3):
            continue
        # Same approved fact + expiry yields one notification for its lifetime.
        key = hashlib.sha256(f"{card.id}:{fact.get('object') or fact.get('value')}:{end.isoformat()}".encode()).hexdigest()
        out.append({"dedupe_key": "expiring:" + key, "kind": "expiring",
                    "title": "What you are looking for expires within 3 days", "href": href + "#memory"})
    if pending:
        out.append({"dedupe_key": f"pending:{card.id}:{now.date().isoformat()}", "kind": "pending",
                    "title": f"{pending} facts waiting for your review", "href": href + "#inbox"})
    if matches:
        year, week, _ = now.isocalendar()
        out.append({"dedupe_key": f"matched:{card.id}:{year}-W{week}", "kind": "matched",
                    "title": "Someone matched your card this week", "href": "/home"})
    return out


def persist_nudges(email: str, card, pending: int | None, now: datetime | None = None, matches: int = 0) -> list[dict]:
    sb = config.get_supabase()
    candidates = nudge_candidates(card, pending, now, matches)
    if candidates:
        sb.table("card_nudges").upsert([
            {**n, "owner_email": email.lower(), "handle": card.handle} for n in candidates
        ], on_conflict="owner_email,dedupe_key", ignore_duplicates=True).execute()
    rows = (sb.table("card_nudges").select("id,kind,title,href,created_at,dedupe_key")
            .eq("owner_email", email.lower()).is_("dismissed_at", "null")
            .gte("created_at", ((now or datetime.now(timezone.utc)) - timedelta(days=7)).isoformat())
            .order("created_at", desc=True).limit(10).execute().data or [])
    active_keys = {n["dedupe_key"] for n in candidates}
    shown, pending_shown = [], False
    for nudge in rows:
        if nudge["kind"] == "matched" and nudge["dedupe_key"] not in active_keys:
            continue
        if nudge["kind"] == "expiring" and nudge["dedupe_key"] not in active_keys:
            continue
        if nudge["kind"] == "pending":
            if not pending or pending_shown:
                continue
            nudge["title"] = f"{pending} facts waiting for your review"
            pending_shown = True
        shown.append(nudge)
    return shown


def duplicates(email: str, row: dict) -> list[dict]:
    # Same-name matches are deliberately insufficient evidence for a merge.
    own = owner_rows(email)
    return [{"id": r["id"], "handle": r["handle"],
             "name": (r.get("card", {}).get("identity") or {}).get("name", ""),
             "status": r["status"]} for r in own if r["id"] != row["id"]]


def unclaimed_duplicates(row: dict) -> list[dict]:
    linkedin = ((row.get("card") or {}).get("identity") or {}).get("links", {}).get("linkedin")
    return cards.claim_candidates_by_linkedin(linkedin) if linkedin else []


async def status(email: str, *, persist: bool = True) -> dict | None:
    row = await asyncio.to_thread(current_row, email)
    if row is None:
        return None
    card = card_from_row(row)
    pending = None
    connected = None
    if config.MEMORY_SERVICE_TOKEN:
        memory, suggestions = await asyncio.gather(
            asyncio.to_thread(zynd_memory.fetch_findability, email),
            zynd_mcp.suggested_facts(email), return_exceptions=True,
        )
        if isinstance(memory, dict):
            connected = memory.get("connected")
        if isinstance(suggestions, list):
            pending = len(suggestions)
        elif isinstance(suggestions, zynd_mcp.MemoryUnavailable) and "no ZYND account" in str(suggestions):
            pending = 0
    metrics, candidates, unclaimed = await asyncio.gather(
        asyncio.to_thread(activity, card.handle), asyncio.to_thread(duplicates, email, row),
        asyncio.to_thread(unclaimed_duplicates, row),
    )
    matches = sum(q["count"] for q in metrics["queries"])
    intro_pending = None
    if config.FEATURE_S12_INTROS and row.get("owner_user_id"):
        try:
            from services import intros
            incoming_status = await intros.persona("/users/" + row["owner_user_id"])
            incoming = incoming_status["intros"]
            intros.require_scope(incoming, row["owner_user_id"])
            await intros.sync(incoming)
            intro_pending = incoming_status["pending_count"]
            metrics = await asyncio.to_thread(activity, card.handle)
        except Exception:
            # An intro outage must not hide fact review/home or imply zero requests.
            pass
    nudges = await asyncio.to_thread(persist_nudges, email, card, pending, matches=matches) if persist else nudge_candidates(card, pending, matches=matches)
    return {"handle": card.handle, "name": card.identity.name, "card_id": card.id,
            "completeness": completeness(card), "inbox_count": pending, "intro_inbox_count": intro_pending,
            "connection": {"memory_connected": connected, "assistants_available": False},
            "sources": [{"platform": s.platform, "scraped_at": s.scraped_at,
                         "state": "stale" if (_parse_ts(s.scraped_at) is None or _parse_ts(s.scraped_at) < datetime.now(timezone.utc) - timedelta(days=30)) else "fresh"}
                        for s in card.sources],
            "activity": metrics, "duplicates": candidates, "unclaimed_duplicates": unclaimed, "nudges": nudges,
            "notification_prefs": {**DEFAULT_PREFS, **(row.get("notification_prefs") or {})},
            "visibility": "public" if row["status"] == "published" else "private"}
