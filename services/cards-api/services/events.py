"""S04 event insert + session hashing. Flag off = no-op."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

import config
from services import ua_class

logger = logging.getLogger(__name__)

ALLOWED_EVENTS = frozenset({
    "view",
    "agent_fetch",
    "share_click",
    "create_start",
    "create_publish",
    "claim_start",
    "claim_done",
    "fact_reported",
    "fact_approved",
    "fact_dismissed",
    "chat_message",
})

_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
_MAX_BATCH = 20
_WINDOW_SECONDS = 60
_MAX_PER_WINDOW = 60
_META_MAX_BYTES = 2048
_hits: dict[str, deque[float]] = defaultdict(deque)

CREATED_VIA = frozenset({"web", "mcp", "import"})


def events_enabled() -> bool:
    return bool(config.FEATURE_S04_EVENTS) and config.SUPABASE_DB_SCHEMA == "cards"


def daily_salt(now: datetime | None = None) -> str:
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    explicit = (config.EVENTS_IP_SALT or "").strip()
    if explicit:
        return hashlib.sha256(f"{explicit}:{day}".encode()).hexdigest()
    secret = (config.SUPABASE_JWT_SECRET or "").encode()
    if not secret:
        return hashlib.sha256(f"s04-fallback:{day}".encode()).hexdigest()
    return hmac.new(secret, day.encode(), hashlib.sha256).hexdigest()


def session_hash_for_ip(ip: str | None, now: datetime | None = None) -> str | None:
    if not ip or not ip.strip():
        return None
    return hashlib.sha256(f"{daily_salt(now)}{ip.strip()}".encode()).hexdigest()


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return None


def sanitize_ref(ref: str | None) -> str | None:
    if not ref or not isinstance(ref, str):
        return None
    cleaned = ref.strip()[:64]
    return cleaned or None


def sanitize_source(source: str | None) -> str | None:
    if not source or not isinstance(source, str):
        return None
    cleaned = source.strip()[:200]
    return cleaned or None


def sanitize_utm(utm: Any) -> dict[str, str] | None:
    if utm is None:
        return None
    if isinstance(utm, str):
        try:
            utm = json.loads(utm)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(utm, dict):
        return None
    out: dict[str, str] = {}
    for key in _UTM_KEYS:
        val = utm.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:128]
    return out or None


def sanitize_created_via(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in CREATED_VIA else None


def sanitize_meta(meta: Any) -> dict | None:
    if meta is None:
        return None
    if not isinstance(meta, dict):
        return None
    try:
        raw = json.dumps(meta, default=str)
    except (TypeError, ValueError):
        return None
    if len(raw.encode()) > _META_MAX_BYTES:
        return None
    return meta


def rate_limited(key: str) -> bool:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > _WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _MAX_PER_WINDOW:
        return True
    q.append(now)
    if len(_hits) > 10_000:
        _hits.clear()
    return False


def _insert_rows(rows: list[dict]) -> None:
    if not rows or not events_enabled():
        return
    try:
        config.get_supabase().table("card_events").insert(rows).execute()
    except Exception:
        logger.exception("card_events insert failed (%d rows)", len(rows))


def _build_row(
    *,
    event: str,
    handle: str | None,
    actor_class: str,
    ref: str | None,
    session_hash: str | None,
    meta: dict | None,
) -> dict:
    return {
        "event": event,
        "handle": (handle or "").strip()[:128] or None,
        "actor_class": actor_class if actor_class in ("human", "ai_agent", "search_bot", "unknown") else "unknown",
        "ref": sanitize_ref(ref),
        "session_hash": session_hash,
        "meta": sanitize_meta(meta),
    }


def insert_batch(
    events: list[dict],
    *,
    user_agent: str | None,
    ip: str | None,
) -> None:
    if not events_enabled() or not events:
        return
    actor = ua_class.classify(user_agent)
    sh = session_hash_for_ip(ip)
    rows = [
        _build_row(
            event=e["event"],
            handle=e.get("handle"),
            actor_class=actor,
            ref=e.get("ref"),
            session_hash=sh,
            meta=e.get("meta"),
        )
        for e in events
    ]
    _insert_rows(rows)


def emit(
    event: str,
    *,
    handle: str | None = None,
    request: Request | None = None,
    ref: str | None = None,
    meta: dict | None = None,
    user_agent: str | None = None,
) -> None:
    """Fire-and-forget single event. Never raises to the caller."""
    if not events_enabled() or event not in ALLOWED_EVENTS:
        return
    ua = user_agent
    ip = None
    if request is not None:
        ua = ua or request.headers.get("user-agent")
        ip = client_ip(request)
    actor = ua_class.classify(ua)
    sh = session_hash_for_ip(ip)
    row = _build_row(
        event=event,
        handle=handle,
        actor_class=actor,
        ref=ref,
        session_hash=sh,
        meta=meta,
    )

    async def _run() -> None:
        try:
            await asyncio.to_thread(_insert_rows, [row])
        except Exception:
            logger.exception("card_events emit failed event=%s", event)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        try:
            _insert_rows([row])
        except Exception:
            logger.exception("card_events emit failed event=%s", event)


def purge_older_than_days(days: int = 180) -> int:
    if not events_enabled():
        return 0
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        resp = (
            config.get_supabase()
            .table("card_events")
            .delete()
            .lt("ts", cutoff)
            .execute()
        )
        return len(resp.data or [])
    except Exception:
        logger.exception("card_events purge failed")
        return 0
