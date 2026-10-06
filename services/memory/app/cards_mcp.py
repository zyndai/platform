"""Cards MCP server — the coding-agent connector for Zynd Cards (streamable-HTTP).

Auth: Bearer JWT only (personal token issued via /v1/service/cards-connect when
a signed-in cards user clicks "Connect MCP" in the dashboard). OAuth discovery
metadata is advertised (RFC 9728) pointing at the main ZYND authorization
server, but v1 has no OAuth flow of its own — the token from the dashboard is
the credential.

Everything a coding agent reports here lands PRIVATE in memory (source_system
"cards_mcp") and flows through the normal extraction pipeline, so the user
reviews it on their card before it goes public. This server never publishes,
never matches, and never exposes other users — it is ingest + own-read only.

Run:  uvicorn app.cards_mcp:app --host 0.0.0.0 --port 8091
"""
import asyncio
from datetime import datetime, timezone

import asyncpg
from arq import create_pool
from arq.connections import RedisSettings
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentAccessToken, Depends
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from pydantic import AnyHttpUrl
from urllib.parse import urlsplit

from app.auth import verify_access_claims
from app.config import settings
from app.models import Turn
from app.services.export import active_context, context_slice
from app.services.findability import get_card
from app.services.ingest import clean_text, ingest_turns

# Process-lifetime pools (same rationale as app.mcp_http: independent of the
# MCP session lifespan, which cycles).
_pool: asyncpg.Pool | None = None
_arq = None
_pool_lock = asyncio.Lock()
_arq_lock = asyncio.Lock()

_REMEMBER_MIN_CHARS = 8
# Guard rail for one report call — a runaway agent must not be able to dump a
# whole codebase into memory.
_MAX_REPORT_CHARS = 4000

SOURCE_SYSTEM = "cards_mcp"

_CARDS_INSTRUCTIONS = """\
You have access to Zynd Cards memory — a feed of durable facts about the user \
you work with, so their public Zynd profile card stays current.

This is a WRITE-FIRST connection: as you learn durable facts about the user \
(their role, skills, languages, projects, tools, goals), report them. Facts \
you report stay private to the user's account until they review and approve \
them for their public card — so report freely, but accurately.

== Tools ==

report_user_info — Use whenever you learn durable facts about the user's \
professional self: role, skills, programming languages, frameworks, projects, \
tools, goals. Pass structured fields where they fit and extra facts as \
notes. Call this once you have several facts; do not call it for every \
keystroke.

remember — Use for a single durable fact the user stated ("I'm learning Rust", \
"I just joined Acme"). Free-form full sentence.

get_my_context — Read what is already known about the user (optionally about \
a topic). Use it to avoid reporting duplicates.

get_my_card — The user's PUBLIC profile facts (what they approved on their \
Zynd card). Use when asked what is public.

== What to report ==

Durable professional facts only: role and title, skills and languages, \
frameworks and tools, projects and side projects, what they are building or \
learning, open-source contributions, domain expertise, goals.

== What NOT to report ==

Secrets, API keys, passwords, tokens, .env contents, file contents, \
credentials — never. Casual chatter, one-off task details, temporary context \
("rename this variable today"). Personal, health, political, financial, or \
location facts unless the user explicitly states them and asks you to.

== Behavior ==

- Do not invent facts. Only report what the user said or what their work \
clearly demonstrates.
- Batch facts: one report_user_info call beats five.
- Do not claim a fact was saved unless the tool returned saved=true.
- If unsure whether something is durable, ask: "Want me to save this to your \
Zynd card memory?"
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


def _uid(token: AccessToken = CurrentAccessToken()) -> str:
    # Fail closed: unlike the main MCP server there is no anonymous surface
    # here at all — every tool requires the cards token.
    if token.client_id == "anonymous":
        raise PermissionError("This tool requires a Zynd Cards MCP connection.")
    return token.client_id


# ── Auth: same verifier contract as app.mcp_http (JWT + revocation). ──────────

class CardsTokenVerifier(TokenVerifier):

    def __init__(self, required_scopes: list[str] | None = None):
        super().__init__(required_scopes=required_scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not token.strip():
            return None
        try:
            user_id, issued_at = verify_access_claims(token)
        except ValueError:
            return None
        pool = await _get_pool()
        from app.services.sessions import tokens_revoked
        if await tokens_revoked(pool, user_id, issued_at):
            return None
        return AccessToken(
            token=token,
            client_id=user_id,
            scopes=["user"],
            claims={"sub": user_id, "iat": issued_at},
        )


auth = RemoteAuthProvider(
    token_verifier=CardsTokenVerifier(required_scopes=["user"]),
    # The main ZYND server is the (only) place tokens for this resource come
    # from; OAuth-capable clients that probe discovery get pointed there.
    authorization_servers=[AnyHttpUrl(settings.public_base_url)],
    base_url=settings.cards_mcp_public_base_url,
    resource_name="Zynd Cards",
)

mcp = FastMCP("zynd-cards", auth=auth, instructions=_CARDS_INSTRUCTIONS)


def _clip(text: str, limit: int = _MAX_REPORT_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit]


def _turn_lines(role: str, lines: list[str]) -> list[Turn]:
    stamp = datetime.now(timezone.utc)
    return [Turn(role="user", content=line, timestamp=stamp) for line in lines]


async def _ingest_lines(uid: str, lines: list[str]) -> tuple[int, int]:
    """Ingest clean, non-empty lines. Returns (inserted, skipped)."""
    turns = _turn_lines("user", [clean_text(ln).strip() for ln in lines
                                 if len(clean_text(ln).strip()) >= _REMEMBER_MIN_CHARS])
    if not turns:
        return 0, 0
    return await ingest_turns(
        await _get_pool(), await _get_arq(), uid, SOURCE_SYSTEM, turns,
        min_chars=_REMEMBER_MIN_CHARS,
    )


def _fmt(inserted: int, skipped: int) -> dict:
    if inserted == 0:
        return {"saved": False, "reason": "nothing new (too short or duplicates)"}
    return {
        "saved": True,
        "note": "Saved privately. The user reviews facts on their Zynd card before "
                "anything becomes public.",
        "items_saved": inserted,
        "items_skipped": skipped,
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def report_user_info(
    role: str = "",
    skills: list[str] | None = None,
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    tools: list[str] | None = None,
    projects: list[str] | None = None,
    goals: str = "",
    notes: str = "",
    uid: str = Depends(_uid),
) -> dict:
    """Report durable professional facts about the user to their Zynd card memory.

    Call whenever you learn facts about the user's professional self — from what
    they say, their commits, or their project files. Facts stay private to the
    user until they review them on their card; report accurately, not exhaustively.

    Fields are optional — pass only what you actually learned:
      role — job title / role ("Senior backend engineer at Acme")
      skills — ["distributed systems", "technical writing"]
      languages — programming languages ["Python", "Go"]
      frameworks — ["FastAPI", "Next.js"]
      tools — ["Postgres", "Redis", "Docker"]
      projects — named projects with one-line descriptions
      goals — what they are building toward or learning next
      notes — any other durable facts, one per line

    Never pass secrets, API keys, passwords, tokens, .env contents, or file
    contents. Never report casual or one-off task details."""
    lines: list[str] = []
    if role := _clip(role, 200):
        lines.append(f"The user's role: {role}")
    for label, values in (("skill", skills), ("programming language", languages),
                          ("framework", frameworks), ("tool", tools)):
        for v in values or []:
            v = _clip(v, 120)
            if v:
                lines.append(f"The user has a {label}: {v}")
    for p in projects or []:
        p = _clip(p, 240)
        if p:
            lines.append(f"The user works on the project: {p}")
    if goals := _clip(goals, 600):
        lines.append(f"The user's goal: {goals}")
    for ln in (notes or "").splitlines():
        ln = _clip(ln)
        if ln:
            lines.append(ln)

    if not lines:
        return {"saved": False, "reason": "nothing to report — pass at least one fact"}
    inserted, skipped = await _ingest_lines(uid, lines)
    return _fmt(inserted, skipped)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def remember(text: str, uid: str = Depends(_uid)) -> dict:
    """Save a single durable fact the user stated, in a complete sentence.

    Use when the user says something like "I'm learning Rust", "I just became
    a tech lead", "remember this". NOT for secrets, passwords, casual chatter,
    or one-off task instructions."""
    text = clean_text(text or "").strip()
    if len(text) < _REMEMBER_MIN_CHARS:
        return {"saved": False,
                "reason": f"too short — pass a full sentence (min {_REMEMBER_MIN_CHARS} chars)"}
    inserted, skipped = await _ingest_lines(uid, [_clip(text)])
    return _fmt(inserted, skipped)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def get_my_context(topic: str | None = None, k: int = 20,
                         uid: str = Depends(_uid)) -> list[dict]:
    """What Zynd already knows about the user (private memory, facts only).

    Call before reporting to avoid duplicates. With `topic`, returns the K most
    relevant facts; without it, the top active facts. Each item has a natural-
    language `statement` — show those, not raw predicate values."""
    pool = await _get_pool()
    k = max(1, min(k, 50))
    if topic and topic.strip():
        return await context_slice(pool, uid, topic.strip(), k)
    return await active_context(pool, uid, k)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def get_my_card(uid: str = Depends(_uid)) -> list[dict]:
    """The user's PUBLIC Zynd card facts — what they approved for discovery.
    Use when asked what is public about them."""
    return await get_card(await _get_pool(), uid)


# ── ASGI app ────────────────────────────────────────────────────────────────────
# uvicorn app.cards_mcp:app --host 0.0.0.0 --port 8091
# Served at /cards-mcp (not /mcp) so a proxy can route /cards-mcp* to this
# process without path rewriting; the well-known metadata then lives at
# /.well-known/oauth-protected-resource/cards-mcp (RFC 9728 path scoping).
app = mcp.http_app(
    path="/cards-mcp",
    stateless_http=True,
    allowed_hosts=[urlsplit(settings.cards_mcp_public_base_url).hostname],
)
