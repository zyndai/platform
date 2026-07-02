"""Hosted, authenticated ZYND MCP server (streamable-HTTP transport).

Any MCP client (Claude Desktop, Cursor, …) connects to https://<host>/mcp with a
ZYND bearer token. The token is verified per request and the tools are scoped to
that authenticated user — there is no trusted user_id parameter, so one user can
never read or change another's data.

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
from app.services import persona
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

_ZYND_INSTRUCTIONS = """\
You have access to ZYND — my cross-AI memory, context, people-discovery, and networking layer.

ZYND is a TWO-WAY system:
1. FEED IT: When I share facts about myself → call remember() so ZYND builds my context graph.
2. READ IT: At the start of every conversation → call get_my_context() so you know who I am and what I'm working on.

If you skip either direction, ZYND cannot help — the graph stays empty and you have no context about me.

== Available ZYND tools ==

remember — Use when I share a durable fact about myself: my role, skills, projects, goals, tools, location, affiliations, interests, beliefs, what I am building, learning, seeking, or open to. Do NOT use for casual chatter, temporary task instructions, secrets, API keys, passwords, private tokens, or one-off details. If I explicitly say "remember this", "save this", or "add this to ZYND", call remember.

get_my_context — Use when I ask what ZYND knows about me, ask you to recall my context, or when my stored context would help answer the current question. Call this EARLY in every conversation. If I ask about a topic, pass that topic. Show the natural-language statements returned.

export_my_context — Use when I ask to export, download, back up, or inspect my full ZYND profile/context graph.

confirm_fact_tool — Use when I confirm that an existing ZYND fact is correct. Pass the exact predicate and object if available from get_my_context.

forget_fact_tool — Use when I say a remembered fact is wrong, outdated, private, should be removed, or should be forgotten. Pass the exact predicate and object if available from get_my_context.

find_similar_users — Use when I ask for people like me, similar users, people building/learning/working on similar things, or people with overlapping context.

find_people — Use when I ask for a target type of person, complementary person, or someone who could help: investors, cofounders, designers, engineers, marketers, mentors, customers, early users, reviewers, domain experts. Convert my intent into a clear natural-language target description.

set_social_links — Use when I ask to save or update public social links: LinkedIn, Instagram, X/Twitter, GitHub.

connect_with — Use when I ask to connect with a person returned by ZYND. Use their user_id from find_similar_users or find_people. If I haven't provided a message, draft a short friendly one and ask for approval unless the intent is clear.

my_connections — Use when I ask who I am connected with, show my connections, or inspect connection status.

send_persona_message — Use when I ask to message an existing ZYND connection. Requires thread_id from my_connections or connect_with. Ask for missing message content.

book_meeting — Use when I ask to schedule, propose, or book a meeting with a ZYND connection. Ask for missing details: thread_id/person, title, start time, end time, timezone, location, description.

publish_page — Use when I ask to turn something into a shareable web page ("make this a page", "publish as HTML"). Pass content as HTML or Markdown.

list_my_pages — Use when I ask to see pages I have published or hosted.

disconnect — Use when I ask to sign out or disconnect ZYND. Revokes all ZYND tokens.

get_my_system_prompt — Use at the START of a conversation. Returns your personalized instructions plus my profile and everything ZYND remembers about me. After loading, if I share anything new, call remember.

== General behavior ==

Do not invent ZYND results. Only report what tools actually return.
Do not claim something was remembered, confirmed, forgotten, connected, messaged, or booked unless the relevant tool succeeded and returned success.
Use ZYND quietly and naturally when helpful, but don't overuse tools.
If a tool fails, explain briefly and continue helping.
If you are unsure whether a fact should be saved, ask: "Do you want me to save this to ZYND?"

== Privacy and safety ==

Treat ZYND as my private memory unless the tool explicitly returns public/matching data.
Never save secrets, API keys, passwords, private tokens, .env contents, or credentials.
Be cautious with health, politics, immigration, legal, financial, identity, and highly personal topics. Ask before saving these.
For matching and people discovery, only use public/findability information returned by ZYND.
Do not reveal raw internal IDs unless needed for a tool call or I ask.

== Preferred flow ==

If I share a durable fact → call remember.
If I ask what you know about me → call get_my_context.
If I ask who is similar to me → call find_similar_users.
If I ask who can help me / who I should meet → call find_people.
If I choose someone to contact → call connect_with.
If I ask about existing relationships → call my_connections.
If I ask to message or meet a connection → call send_persona_message or book_meeting.
"""


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
    instructions=_ZYND_INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def remember(text: str) -> dict:
    """THIS IS HOW ZYND FEEDS. Call whenever the user shares a durable fact about
    themselves — role, skills, projects, goals, tools, location, affiliations,
    interests, beliefs, what they are building, learning, seeking, or open to.

    WITHOUT THIS the context graph stays empty and ZYND cannot help. Every durable
    fact you skip is permanently invisible to future conversations.

    Do NOT use for: casual chatter, temporary task instructions, secrets, API keys,
    passwords, private tokens, or one-off details.

    If the user explicitly says "remember this", "save this", or "add this to ZYND",
    call this tool immediately.

    Pass a complete sentence in the user's voice. ZYND extracts structured facts in
    the background; they then appear in get_my_context and power find_similar_users.
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
    """YOUR WINDOW INTO WHO THE USER IS. Call this at the START of every
    conversation so you know the user's role, projects, skills, and what
    they are working on. Without this, you are flying blind.

    With `topic`, returns the K facts most relevant to it; with no topic,
    returns top active facts overall — use the topic-less form to answer
    "what do you know about me?". Returns [] if the profile is empty — tell
    the user to share facts about themselves so you can call `remember`.

    Each fact carries a natural-language `statement` (e.g. "You're building
    a micro-SaaS"). Show the `statement` text to the user; do NOT surface
    raw predicate or confidence values."""
    pool = await _get_pool()
    k = max(1, min(k, 50))
    if topic and topic.strip():
        return await context_slice(pool, _uid(), topic.strip(), k)
    return await active_context(pool, _uid(), k)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def export_my_context() -> dict:
    """Export the full active context graph as JSON-LD. Use when the user asks to
    export, download, back up, or inspect their complete ZYND profile."""
    return await build_jsonld_export(await _get_pool(), _uid())


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_similar_users(cluster_type: str = "intent_cluster", k: int = 10) -> list[dict]:
    """Find people with overlapping context. Use when the user asks for people
    like them, similar users, or people building/learning/working on similar
    things. cluster_type: intent_cluster, skill_cluster, belief_cluster,
    concept_cluster, full_context."""
    return await match_users(await _get_pool(), _uid(), cluster_type, max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_people(target: str, k: int = 10) -> list[dict]:
    """Find FINDABLE ZYND users matching a TARGET PROFILE — complementary people,
    not people like the user. Use when the user asks for investors, cofounders,
    designers, engineers, marketers, mentors, customers, domain experts, etc.

    Pass a natural-language target description (e.g. "seed-stage investor who
    backs dev-tools", "growth marketer for micro-SaaS"). Convert the user's
    intent into the target profile. Returns [] if no one matches.

    Use find_similar_users instead for "people like me" / overlapping context.
    The returned user_id can be passed to connect_with."""
    return await search_by_query(await _get_pool(), _uid(), target, limit=max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def confirm_fact_tool(predicate: str, object: str) -> dict:
    """Confirm an existing ZYND fact is correct. Use when the user confirms
    something ZYND remembers about them. Pass the exact predicate and object
    as returned by get_my_context."""
    return {"confirmed": await confirm_fact(await _get_pool(), _uid(), predicate, object)}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
async def forget_fact_tool(predicate: str, object: str) -> dict:
    """Remove a ZYND fact. Use when the user says something ZYND remembers is
    wrong, outdated, private, should be removed, or should be forgotten.
    Pass the exact predicate and object as returned by get_my_context."""
    return {"forgotten": await forget_fact(await _get_pool(), _uid(), predicate, object)}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def publish_page(content: str, title: str = "", format: str = "html",
                       visibility: str = "unlisted") -> dict:
    """Host an HTML or Markdown page and return a public share URL. Use when the
    user asks to turn something into a shareable web page ("make this a page",
    "publish this"). Pass the full body as `content`; set `format` to "html"
    or "markdown". Returns {success, url, slug, title}. Show the `url` to the user."""
    from app.services import pages
    return await pages.create_page(await _get_pool(), _uid(), content, title, format, visibility)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def list_my_pages() -> list[dict]:
    """List hosted shareable pages, newest first. Use when the user asks to
    see pages they have published."""
    from app.services import pages
    return await pages.list_pages(await _get_pool(), _uid())


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def disconnect() -> dict:
    """Sign out of ZYND — revoke all ZYND tokens (web, GPT, MCP clients).
    The user will need to reconnect to use ZYND again."""
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
    """Save or update public social links: LinkedIn, Instagram, X/Twitter, GitHub.
    Use when the user asks to save, update, or add their social profile links."""
    from app.services import social
    return await _social(social.set_social, {"linkedin": linkedin, "instagram": instagram, "twitter": x, "github": github})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def connect_with(user_id: str, message: str = "Hi — we matched on ZYND, would love to connect.") -> dict:
    """Send a connection request to a matched person by their user_id from
    find_similar_users or find_people. If the user hasn't provided a message,
    draft a short friendly one and ask for approval unless the intent is clear.
    Routed through the persona network (works even if the target is offline)."""
    from app.services import social
    return await _social(social.connect, user_id, message)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def send_persona_message(thread_id: str, content: str) -> dict:
    """Send a message to an existing connection. Requires thread_id from
    my_connections or connect_with. Ask for missing message content if needed."""
    from app.services import social
    return await _social(social.send_message, thread_id, content)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def my_connections() -> dict:
    """List the user's ZYND connections on the persona network. Use when the
    user asks who they are connected with or to inspect connection status."""
    from app.services import social
    return await _social(social.connections)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def book_meeting(thread_id: str, title: str, start_time: str, end_time: str,
                       location: str = "", description: str = "") -> dict:
    """Propose a meeting with a connection (thread_id from my_connections).
    Times are ISO-8601. Accepting auto-books on both Google Calendars via persona.
    Ask for missing details: title, start time, end time, timezone, location."""
    from app.services import social
    payload = {"title": title, "start_time": start_time, "end_time": end_time,
               "location": location, "description": description}
    return await _social(social.book_meeting, thread_id, payload)


def _format_system_prompt(user: dict | None, persona_status: dict | None, facts: list[dict]) -> str:
    display_name = (user.get("display_name") or "the user") if user else "the user"
    persona_name = (persona_status.get("name") or display_name) if persona_status else display_name
    profile = (persona_status.get("profile") or {}) if persona_status else {}

    lines = [
        "You are an AI assistant with access to ZYND — the user's cross-AI memory,",
        "context graph, people-discovery, and networking layer.\n",
        "== WHO YOU REPRESENT ==",
        f"Principal: {persona_name}",
    ]

    description = (persona_status.get("description") or "").strip() if persona_status else ""
    if description:
        lines.append(f"About them: {description}")

    title = (profile.get("title") or "").strip()
    organization = (profile.get("organization") or "").strip()
    if title and organization:
        lines.append(f"Role: {title} at {organization}")
    elif title:
        lines.append(f"Role: {title}")
    elif organization:
        lines.append(f"Organization: {organization}")

    location = (profile.get("location") or "").strip()
    if location:
        lines.append(f"Location: {location}")

    capabilities = persona_status.get("capabilities", []) if persona_status else []
    if capabilities:
        if isinstance(capabilities, list):
            lines.append(f"Expertise: {', '.join(str(c) for c in capabilities if str(c).strip())}")
        elif isinstance(capabilities, str) and capabilities.strip():
            lines.append(f"Expertise: {capabilities}")

    interests = profile.get("interests", []) if persona_status else []
    if interests:
        if isinstance(interests, list):
            lines.append(f"Interests: {', '.join(str(i) for i in interests if str(i).strip())}")
        elif isinstance(interests, str) and interests.strip():
            lines.append(f"Interests: {interests}")

    social_keys = [
        ("linkedin", "LinkedIn"), ("instagram", "Instagram"),
        ("twitter", "X/Twitter"), ("github", "GitHub"),
        ("website", "Website"),
    ]
    social_found = []
    for key, label in social_keys:
        url = (profile.get(key) or "").strip()
        if url:
            social_found.append(f"{label}: {url}")
    if social_found:
        lines.append("\n== SOCIAL LINKS ==")
        lines.extend([f"- {s}" for s in social_found])

    if facts:
        lines.append("\n== WHAT ZYND REMEMBERS ABOUT YOUR PRINCIPAL ==")
        for f in facts:
            stmt = (f.get("statement") or "").strip()
            if stmt:
                lines.append(f"- {stmt}")

    lines.extend([
        "\n== YOUR ZYND TOOLKIT ==",
        "You have ZYND tools available through MCP. Use them proactively.",
        "CRITICAL TWO-WAY FLOW:",
        "  1. FEED: When the user shares a new durable fact about themselves → call remember().",
        "     If you skip this, the context graph stays empty forever for that fact.",
        "  2. FETCH: Use get_my_context() to know who the user is — without it, you're blind.",
        "",
        "Key tools:",
        "  remember — save durable facts about the user (NOT secrets, passwords, casual chatter)",
        "  get_my_context — recall what ZYND knows about the user",
        "  find_similar_users — find people with overlapping context",
        "  find_people — find people by target profile (investors, cofounders, experts, etc.)",
        "  connect_with — send a connection request to a matched person",
        "  publish_page — host content as a shareable web page",
        "",
        "Rules:",
        "  - Never claim something was remembered/connected/booked unless the tool returned success.",
        "  - Never save secrets, API keys, passwords, credentials, or .env contents.",
        "  - Ask before saving health, political, legal, financial, or highly personal facts.",
        "  - If unsure whether to save, ask: 'Do you want me to save this to ZYND?'",
        "  - If the user shares anything new about themselves → call remember.",
    ])

    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def get_my_system_prompt() -> str:
    """Load your personalized ZYND profile so you know exactly who the user is and
    what ZYND remembers about them. Call this at the START of every conversation.

    Returns your full instructions plus the user's persona profile and all context
    facts ZYND has stored. After loading, if the user shares ANYTHING new about
    themselves, call `remember` to feed it back into ZYND."""
    uid = _uid()
    pool = await _get_pool()

    user = await pool.fetchrow(
        "SELECT display_name, supabase_user_id, persona_agent_id FROM users WHERE id = $1", uid
    )

    persona_status = None
    if user and user["supabase_user_id"]:
        try:
            persona_status = await persona.get_status(user["supabase_user_id"])
        except Exception:
            persona_status = None

    facts = await active_context(pool, uid, k=20)

    return _format_system_prompt(dict(user) if user else None, persona_status, facts)


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
