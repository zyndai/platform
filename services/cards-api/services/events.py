"""S04 event insert + session hashing. Flag off = no-op."""
from __future__ import annotations

import asyncio
import atexit
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

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
    "question_answered",
    "first_win_ask",
    "first_win_looking",
    "first_win_share",
    "first_win_connect",
    "claim_start",
    "claim_done",
    "fact_reported",
    "fact_approved",
    "fact_dismissed",
    "chat_message",
    # Click on the public card's "Get your own" bar; create_start still fires only when a build starts.
    "visitor_cta_click",
})

# Emitted only by the API itself. Kept out of ALLOWED_EVENTS so the unauthenticated POST /events
# cannot forge them and distort the networking funnel.
AI_READ_ALERT_EVENT = "ai_read_alert_sent"

SERVER_EVENTS = frozenset({
    "search",
    "search_result_action",
    # The AI-read email throttle (services/ai_read_alerts.py): a forged row would silence an
    # owner's alerts for a whole cooldown window.
    AI_READ_ALERT_EVENT,
})

# Who ran a search: the Cards website, Memory's find_people for a signed-in owner, the public
# Cards MCP, or an agent calling /ask. Unknown or absent means the endpoint's own default. A caller can claim any of these, which is fine for a
# count of searches; only the server-emitted search_result_action below is relied on.
SEARCH_VIA = frozenset({"web", "memory", "mcp", "ask"})
RESULT_SOURCES = frozenset({"card", "zynd", "linkedin"})
RESULT_ACTIONS = frozenset({"connect", "invite"})

_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
_MAX_BATCH = 20
_WINDOW_SECONDS = 60
_MAX_PER_WINDOW = 60
_META_MAX_BYTES = 2048
_EVENT_WRITE_TIMEOUT_SECONDS = 10
_hits: dict[str, deque[float]] = defaultdict(deque)

CREATED_VIA = frozenset({"web", "mcp", "import", "invite"})


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


def attributed_meta(meta: Any, user_agent: str | None) -> dict:
    """Derive the advertised agent from the header, overriding payload claims."""
    clean = dict(sanitize_meta(meta) or {})
    clean.pop("agent_name", None)
    clean.pop("client_name", None)
    name = ua_class.agent_name(user_agent)
    attribution = {}
    if name:
        attribution["agent_name"] = name
    elif ua_class.classify(user_agent) == "unknown":
        attribution["client_name"] = ua_class.unidentified_client(user_agent)
    clean.update(attribution)
    # Preserve attribution even if adding the label exceeds the metadata limit.
    return sanitize_meta(clean) or attribution


@lru_cache(maxsize=1)
def _event_store():
    """Isolate background writes from the shared client's HTTP/2 connections."""
    import httpx
    from supabase import ClientOptions, create_client

    transport = httpx.Client(http1=True, http2=False, timeout=_EVENT_WRITE_TIMEOUT_SECONDS)
    atexit.register(transport.close)
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY,
                         options=ClientOptions(schema=config.SUPABASE_DB_SCHEMA,
                                               httpx_client=transport))


def _insert_rows(rows: list[dict]) -> bool:
    if not rows or not events_enabled():
        return True
    try:
        _event_store().table("card_events").insert(rows).execute()
    except Exception:
        logger.exception("card_events insert failed (%d rows)", len(rows))
        return False
    if config.FEATURE_AI_READ_ALERTS:
        from services import ai_read_alerts
        ai_read_alerts.schedule(rows)
    return True


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
) -> bool:
    if not events_enabled() or not events:
        return True
    actor = ua_class.classify(user_agent)
    sh = session_hash_for_ip(ip)
    rows = [
        _build_row(
            event=e["event"],
            handle=e.get("handle"),
            actor_class=actor,
            ref=e.get("ref"),
            session_hash=sh,
            # Only the validated chat handler may populate owner question history.
            meta=attributed_meta({k: v for k, v in (e.get("meta") or {}).items()
                  if k not in {"question", "question_truncated", "question_source"}} if isinstance(e.get("meta"), dict) else None,
                  user_agent),
        )
        for e in events
    ]
    return _insert_rows(rows)


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
    if not events_enabled() or event not in ALLOWED_EVENTS | SERVER_EVENTS:
        return
    ua = user_agent
    ip = None
    if request is not None:
        ua = ua or request.headers.get("user-agent")
        ip = client_ip(request)
    if event in {"view", "agent_fetch"} and ua == ua_class.INTERNAL_CARDS_CLIENT:
        return
    actor = ua_class.classify(ua)
    sh = session_hash_for_ip(ip)
    row = _build_row(
        event=event,
        handle=handle,
        actor_class=actor,
        ref=ref,
        session_hash=sh,
        meta=attributed_meta(meta, ua),
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


def search_context(search_id: str | None, via: str | None, default: str = "web") -> tuple[str, str]:
    """(search id, via) for one search: the caller's id when it is a UUID, else a new one."""
    try:
        sid = str(UUID((search_id or "").strip()))
    except ValueError:
        sid = str(uuid4())
    kind = (via or "").strip().lower()
    return sid, kind if kind in SEARCH_VIA else default


def record_search(request: Request, results: list[dict], *, has_query: bool, search_id: str, via: str,
                  **filters: str) -> None:
    """Top of the networking funnel (docs/cards/s04-funnel.sql): how many searches, how many
    people came back, which ones. No query text and no caller identity is stored."""
    emit(
        "search",
        request=request,
        meta={
            "n": len(results),
            "top": [r["handle"] for r in results[:5] if r.get("handle")],
            "filters": sorted(name for name, value in filters.items() if value),
            "text": has_query,
            "search_id": search_id,
            "via": via,
        },
    )


def record_result_action(*, search_id: str, rank: int, source: str, action: str, handle: str | None,
                         connection_id: str | None = None, invite_id: str | None = None) -> None:
    """A search led to a connection request or an invitation (the next step of the funnel).
    Emitted by the server for a trusted caller (Memory), never accepted from POST /events; carries
    the search it came from, never the query or a user."""
    if source not in RESULT_SOURCES or action not in RESULT_ACTIONS:
        return
    meta: dict = {"search_id": search_id, "rank": rank, "source": source, "action": action}
    if connection_id:
        meta["connection_id"] = connection_id
    if invite_id:
        meta["invite_id"] = invite_id
    emit("search_result_action", handle=handle, meta=meta)


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
        # Same retention as analytics. Absence of the optional visitor tables
        # must not prevent the established card-event cleanup.
        try:
            config.get_supabase().table("profile_visits").delete().lt("visited_at", cutoff).execute()
        except Exception:
            logger.warning("profile_visits purge unavailable")
        return len(resp.data or [])
    except Exception:
        logger.exception("card_events purge failed")
        return 0
