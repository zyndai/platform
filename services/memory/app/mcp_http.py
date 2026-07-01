"""Hosted, authenticated ZYND MCP server (streamable-HTTP transport).

Remote version of app/mcp_server.py: any MCP client (Claude Desktop, Cursor, …)
connects to https://<host>/mcp with a ZYND bearer token. The token is verified per
request and the tools are scoped to that authenticated user — there is no trusted
user_id parameter, so one user can never read or change another's data.

Run:  uvicorn app.mcp_http:app --host 0.0.0.0 --port 8090
"""
import asyncio
import contextvars
from datetime import datetime, timezone

import asyncpg
from arq import create_pool
from arq.connections import RedisSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.auth import verify_access_claims
from app.config import settings
from app.models import Turn
from app.services.control import confirm_fact, forget_fact
from app.services.export import active_context, build_jsonld_export, context_slice
from app.services.ingest import clean_text, ingest_turns
from app.services.matching import match_users, search_by_query

# Set by the auth ASGI wrapper per request; read by the tools.
_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_user", default=None)

# Process-lifetime pools, independent of the MCP session lifespan (which cycles).
# Locks make lazy init safe under concurrent first requests (no leaked pool).
_pool: asyncpg.Pool | None = None
_arq = None
_pool_lock = asyncio.Lock()
_arq_lock = asyncio.Lock()

# Minimum length for an intentional `remember` write. Lower than the §7.2 chat-noise
# floor (40) because these are deliberate single facts, but still guards empty/junk.
_REMEMBER_MIN_CHARS = 8


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    return _pool


async def _get_arq():
    global _arq
    if _arq is None:
        async with _arq_lock:
            if _arq is None:
                _arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq


def _uid() -> str:
    uid = _current_user.get()
    if uid is None:
        raise RuntimeError("not authenticated")
    return uid


# DNS-rebinding protection is for browser attacks; our clients aren't browsers and
# every request needs a bearer token, so we run behind Caddy's HTTPS + our own auth.
mcp = FastMCP(
    "zynd", stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def remember(text: str) -> dict:
    """Save something the user just told you about themselves into their ZYND memory.

    Call this whenever the user shares a durable fact about themselves — what they are
    building, learning, using, believing, intending, their role, skills, or goals
    (e.g. "I'm learning Rust", "I'm building an AI agent marketplace"). Pass a complete
    sentence in the user's voice. ZYND extracts structured facts in the background; they
    then appear in get_my_context and power find_similar_users. This is how the user's
    context graph gets built from a conversation — without it, their profile stays empty.
    """
    text = clean_text(text or "").strip()
    if len(text) < _REMEMBER_MIN_CHARS:
        return {"saved": False, "reason": f"too short — pass a full sentence (min {_REMEMBER_MIN_CHARS} chars)"}
    turn = Turn(role="user", content=text, timestamp=datetime.now(timezone.utc))
    inserted, skipped = await ingest_turns(
        await _get_pool(), await _get_arq(), _uid(), "claude", [turn],
        min_chars=_REMEMBER_MIN_CHARS,
    )
    if inserted == 0:
        return {"saved": False, "reason": "already remembered (duplicate)"}
    return {"saved": True, "note": "Saved. Facts are extracted in the background; "
            "recall with get_my_context in a few seconds."}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def get_my_context(topic: str | None = None, k: int = 20) -> list[dict]:
    """Facts about the signed-in user. With `topic`, returns the K facts most relevant
    to it; with no topic, returns their top active facts overall — use the topic-less
    form to answer "what do you know about me?". Returns [] if the profile is empty
    (the user hasn't fed ZYND anything yet — see the `remember` tool).

    Each fact carries a natural-language `statement` (e.g. "You're building a micro-SaaS").
    Show the `statement` text to the user; do NOT surface the raw predicate or confidence."""
    pool = await _get_pool()
    k = max(1, min(k, 50))
    if topic and topic.strip():
        return await context_slice(pool, _uid(), topic.strip(), k)
    return await active_context(pool, _uid(), k)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def export_my_context() -> dict:
    """Export the signed-in user's full active context as a JSON-LD packet."""
    return await build_jsonld_export(await _get_pool(), _uid())


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_similar_users(cluster_type: str = "intent_cluster", k: int = 10) -> list[dict]:
    """Find people whose active context overlaps the signed-in user's. cluster_type:
    intent_cluster, skill_cluster, belief_cluster, concept_cluster, full_context."""
    return await match_users(await _get_pool(), _uid(), cluster_type, max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_people(target: str, k: int = 10) -> list[dict]:
    """Find FINDABLE ZYND users who match a DESCRIBED TARGET PROFILE — the kind of
    person the signed-in user is looking FOR (complementary), NOT people like them.

    Pass a natural-language description of the target's role / expertise / what they
    offer (e.g. "seed-stage investor who backs dev-tools", "growth marketer who can
    help a micro-SaaS with distribution"). YOU do the role reasoning
    (founder→investor, SaaS→distribution); ZYND returns users whose PUBLIC findability
    profile is nearest to that description. Returns [] if no one matches.

    Use find_similar_users instead when the user wants "people like me" / "who is
    building what I am". The returned user_id can be passed to connect_with."""
    return await search_by_query(await _get_pool(), _uid(), target, limit=max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def confirm_fact_tool(predicate: str, object: str) -> dict:
    """Confirm one of the user's facts is true -> raises its confidence to the max."""
    return {"confirmed": await confirm_fact(await _get_pool(), _uid(), predicate, object)}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
async def forget_fact_tool(predicate: str, object: str) -> dict:
    """Forget one of the user's facts -> soft-deleted (kept for audit, no longer active)."""
    return {"forgotten": await forget_fact(await _get_pool(), _uid(), predicate, object)}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def publish_page(content: str, title: str = "", format: str = "html",
                       visibility: str = "unlisted") -> dict:
    """Host an HTML or Markdown page for the signed-in user and return a public share URL.

    Use when the user asks to turn something into a shareable web page ("make this a page I
    can send", "publish this as HTML"). Pass the full body as `content`; set `format` to
    "html" or "markdown". Returns {success, url, slug, title}. Show the `url` to the user."""
    from app.services import pages
    return await pages.create_page(await _get_pool(), _uid(), content, title, format, visibility)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def list_my_pages() -> list[dict]:
    """List the shareable pages the signed-in user has hosted (newest first)."""
    from app.services import pages
    return await pages.list_pages(await _get_pool(), _uid())


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def disconnect() -> dict:
    """Sign out of ZYND — revokes this token and all your other ZYND tokens (web, GPT,
    other MCP clients). You'll need to reconnect / sign in again to use ZYND."""
    from app.services.sessions import revoke_user_tokens
    await revoke_user_tokens(await _get_pool(), _uid())
    return {"status": "signed_out", "note": "Reconnect ZYND to sign back in."}


# ---- persona network: connect / message / meet (gated by persona_enabled) ----

async def _social(op, *args) -> dict:
    """Run a social/persona op, turning the gate + identity + network errors into a
    friendly result instead of a tool exception."""
    from app.services.social import SocialDisabled
    from app.services.persona import PersonaError
    try:
        result = await op(await _get_pool(), _uid(), *args)
        return {"ok": True, "result": result}
    except SocialDisabled as exc:
        return {"ok": False, "reason": str(exc), "hint": "persona connect/message is coming soon"}
    except (ValueError, PersonaError) as exc:
        return {"ok": False, "reason": str(exc)}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def set_social_links(linkedin: str = "", instagram: str = "", x: str = "", github: str = "") -> dict:
    """Save your public social links (LinkedIn / Instagram / X / GitHub) — shown to people you match with."""
    from app.services import social
    return await _social(social.set_social, {"linkedin": linkedin, "instagram": instagram, "twitter": x, "github": github})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def connect_with(user_id: str, message: str = "Hi — we matched on ZYND, would love to connect.") -> dict:
    """Send a connection request to a matched person, by their user_id from find_similar_users.
    Routed through their persona (works even if they are offline)."""
    from app.services import social
    return await _social(social.connect, user_id, message)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def send_persona_message(thread_id: str, content: str) -> dict:
    """Send a message in an existing connection thread (thread_id from connect_with / my_connections)."""
    from app.services import social
    return await _social(social.send_message, thread_id, content)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def my_connections() -> dict:
    """List the people you are connected with on the persona network."""
    from app.services import social
    return await _social(social.connections)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def book_meeting(thread_id: str, title: str, start_time: str, end_time: str,
                       location: str = "", description: str = "") -> dict:
    """Propose a meeting with a connection (thread_id from my_connections). Times are ISO-8601.
    Accepting auto-books on both Google Calendars via persona."""
    from app.services import social
    payload = {"title": title, "start_time": start_time, "end_time": end_time,
               "location": location, "description": description}
    return await _social(social.book_meeting, thread_id, payload)


_mcp_app = mcp.streamable_http_app()  # Starlette app (handles its own session lifespan)


async def app(scope, receive, send):
    """Pure-ASGI auth wrapper. Pure ASGI (not BaseHTTPMiddleware) so the contextvar
    set here propagates into the tool call. Non-http scopes (lifespan) pass through."""
    if scope["type"] != "http":
        await _mcp_app(scope, receive, send)
        return

    headers = dict(scope.get("headers") or [])
    scheme, _, value = headers.get(b"authorization", b"").decode().partition(" ")
    token = value.strip() if scheme.lower() == "bearer" else ""  # RFC 6750: case-insensitive
    try:
        user_id, issued_at = verify_access_claims(token)
    except ValueError:
        await _send_401(send)
        return
    from app.services.sessions import tokens_revoked
    if await tokens_revoked(await _get_pool(), user_id, issued_at):
        await _send_401(send)
        return
    _current_user.set(user_id)
    await _mcp_app(scope, receive, send)


async def _send_401(send) -> None:
    body = b'{"error":"unauthorized - supply a valid ZYND bearer token"}'
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
