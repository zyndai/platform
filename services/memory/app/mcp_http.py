"""Hosted, authenticated ZYND MCP server (streamable-HTTP transport).

Auth supports two modes simultaneously:
  1. Bearer JWT (existing clients, Cursor, VS Code, SDKs)
  2. OAuth 2.1 with PKCE + DCR (Claude Desktop/Web/Mobile connectors)

FastMCP's RemoteAuthProvider advertises OAuth discovery so Claude auto-discovers
auth. The ZyndTokenVerifier handles both token types transparently.

Run:  uvicorn app.mcp_http:app --host 0.0.0.0 --port 8090
"""
import asyncio
import base64
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from arq import create_pool
from arq.connections import RedisSettings
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentAccessToken, Depends
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from mcp.types import Icon
from pydantic import AnyHttpUrl

from urllib.parse import urlsplit

from app.auth import verify_access_meta
from app.config import settings
from app.models import Turn
from app.services import card_sync
from app.services.control import confirm_fact, forget_fact, near_matches
from app.services.export import active_context, build_jsonld_export, context_slice
from app.services.findability import get_card
from app.services.ingest import clean_text, ingest_turns
from app.services import people_search
from app.services.matching import match_users
from app.services.self_context import load_self_context, normalize_profile, read_brief


# ── Agent-persona ported MCP tools ─────────────────────────────────────────────
from app.tools import brief as brief_tools
from app.tools import cards_network as cards_network_tools
from app.tools import zynd_services as zynd_services_tools

# Process-lifetime pools, independent of the MCP session lifespan (which cycles).
# Locks make lazy init safe under concurrent first requests (no leaked pool).
_pool: asyncpg.Pool | None = None
_arq = None
_pool_lock = asyncio.Lock()
_arq_lock = asyncio.Lock()

# Minimum length for an intentional `remember` write. Lower than the §7.2 chat-noise
# floor (40) because these are deliberate single facts, but still guards empty/junk.
_REMEMBER_MIN_CHARS = 8
_MAX_REPORT_CHARS = 4000
_CARDS_SOURCE = "cards_mcp"

# Typed-capture flood guards: one report_user_info call may carry at most this
# many values per field and in total, so an agent inferring a whole stack from
# a single sentence cannot fill the owner's review inbox in one call.
MAX_PER_FIELD = 4
MAX_TYPED_TOTAL = 12

_ZYND_INSTRUCTIONS = """\
ZYND is your private cross-AI memory, profile, people discovery, and networking layer. It works two ways: read useful context from it, and save durable facts the user explicitly shares.

READ - exactly one self-info tool: call get_my_context at conversation start. It returns identity, profile, socials, brief, private facts, and the approved public card in one bounded packet. Pass topic for focused facts. There is no other self-info read tool; identity.name is a display label, not necessarily a verified real name. Identity alone does not establish stored facts; null optional sections can mean unavailable.

WRITE - exactly one durable-fact tool: use report_user_info with typed fields at milestones, or text alone for one free-text fact. These modes are mutually exclusive. Batch facts and never call on every keystroke. Only save facts explicitly stated by the user; never infer a stack from a project mention. Never save secrets, credentials, casual chatter, repo paths, or one-off task details.

CORRECT: confirm_fact_tool and forget_fact_tool use the exact predicate and object from get_my_context.facts; never claim success on a false result.
EXPORT: export_my_context only for an explicit backup, download, or export request.
PEOPLE / CARDS NETWORK: find_people returns one list of people from the Cards index (claimed and unclaimed Cards, Zynd members, and LinkedIn only when too few strong matches exist); connect to a result with its handle. A people:message token can send and decide Cards-native connection requests, DM accepted Cards connections, create groups, invite connected Cards (invitees must accept), and message groups. Never claim a request, invitation, or message succeeded unless the tool says so.
CARD OWNER: list_pending_facts, approve_fact, dismiss_fact, set_looking_for, and list_intros when granted by the token. Change headlines in the card editor.

Use only tools visible in the client's actual tool list; export and hosted-page tools retain their existing legacy user scope requirement. Do not search for unavailable tools.
Facts remain private until the user approves them on their card; say so when saving. Only card is public approved context; facts, profile, and brief are private. Ask before saving sensitive topics. Never invent tool results or claim saves, corrections, messages, or bookings succeeded unless their result says so; explain failures briefly.
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


# ── Dependency injection: extract user_id from the authenticated token ──────────
# Tools use `uid: str = Depends(_uid)` to get the current user. This replaces the
# old ContextVar pattern. FastMCP injects the AccessToken automatically when auth
# is configured on the server.

def _uid(token: AccessToken = CurrentAccessToken()) -> str:
    # Every tool requires a dashboard-minted personal token. Empty bearers are
    # rejected in ZyndTokenVerifier (no anonymous AccessToken).
    if not token.client_id or token.client_id == "anonymous":
        raise PermissionError("This tool requires signing in to ZYND.")
    return token.client_id


async def _suid(uid: str = Depends(_uid)) -> str:
    """Resolve memory-layer uid → Supabase user_id for OAuth-backed tools.

    api_tokens (Google, Twitter, LinkedIn, Notion…) is keyed by the Supabase
    user_id, not the memory-layer internal user_id. Without this conversion the
    token lookup in get_tokens() comes back empty and every OAuth tool fails with
    "Google not connected" even when the user connected their account in the
    persona dashboard.
    """
    pool = await _get_pool()
    row = await pool.fetchrow("SELECT supabase_user_id FROM users WHERE id = $1", uid)
    if row and row["supabase_user_id"]:
        return str(row["supabase_user_id"])
    return uid


# ── Auth: custom token verifier ─────────────────────────────────────────────────
# Validates both ZYND HS256 JWTs (for existing clients) and OAuth opaque tokens
# stored in the database (for Claude connectors). Also enforces per-user token
# revocation (tokens_revoked_at watermark).

class ZyndTokenVerifier(TokenVerifier):

    def __init__(self, required_scopes: list[str] | None = None, audiences: list[str] | None = None):
        """`audiences` overrides the JWT audiences this server accepts. The Claude
        plugin server passes only its own resource; nothing else accepts that one."""
        super().__init__(required_scopes=required_scopes)
        self._audiences = audiences
        self._log = logging.getLogger("zynd.mcp_verify")

    async def verify_token(self, token: str) -> AccessToken | None:
        # No anonymous surface. Empty or whitespace bearers are a hard reject.
        # Unauthenticated publish_page is gone.
        if not token or not token.strip():
            return None

        # 1) ZYND JWT — the persona dashboard mints this personal token. Connector
        #    OAuth tokens are accepted alongside legacy ones: they carry the AS
        #    issuer (PUBLIC_BASE_URL) and the RFC 8707 resource audience.
        try:
            meta = verify_access_meta(
                token,
                allowed_audiences=self._audiences or ["zynd", settings.mcp_resource_url, settings.plugin_resource_url],
                allowed_issuers=[settings.jwt_issuer, settings.public_base_url.rstrip("/")],
            )
        except ValueError as exc:
            self._log.warning("JWT verification failed (trying opaque fallback): %s", exc)
            pass
        else:
            user_id = meta["sub"]
            issued_at = meta["iat"]
            ver = meta["ver"]
            pool = await _get_pool()
            from app.services.sessions import token_rejected
            if await token_rejected(pool, user_id, issued_at, ver):
                self._log.warning("JWT rejected: revocation/version mismatch for user %s", user_id)
                return None
            jti = meta.get("jti")
            if jti:
                from app.services.mcp_clients import client_revoked, touch_client
                if await client_revoked(pool, jti, user_id):
                    self._log.warning("JWT rejected: client %s revoked", jti)
                    return None
                if not meta.get("oauth_client_id"):
                    label = await pool.fetchval("SELECT label FROM mcp_clients WHERE jti = $1::uuid", jti)
                    if label == "ZYND ChatGPT plugin":
                        return None  # Old plugin grants require reconnection under reduced scopes.
                await touch_client(pool, jti)
            from plugin_mcp import PLUGIN_SCOPES
            scopes = meta.get("scopes") or ["user"]
            oauth_client_id = meta.get("oauth_client_id")
            if oauth_client_id == settings.plugin_oauth_client_id and (
                not settings.feature_plugin_consent or set(scopes) != set(PLUGIN_SCOPES)
                or meta.get("aud") != settings.plugin_resource_url
            ):
                return None
            claude_plugin = meta.get("aud") == settings.claude_plugin_resource_url
            if claude_plugin and (
                not (settings.feature_claude_plugin and settings.feature_plugin_consent)
                or set(scopes) != set(PLUGIN_SCOPES) or not jti
            ):
                return None
            self._log.debug("accepted token: user=%s iss-scopes=%s", user_id, scopes)
            return AccessToken(
                token=token,
                client_id=user_id,
                scopes=scopes,
                expires_at=meta.get("exp"),
                # RFC 8707 resource binding: newer FastMCP/SDK releases reject
                # tokens whose `resource` doesn't match the resource-server URL.
                # Every accepted audience (legacy "zynd" or the MCP resource)
                # is valid for this server, so bind to the canonical resource.
                resource=settings.claude_plugin_resource_url if claude_plugin else settings.mcp_resource_url,
                subject=str(user_id),
                claims={
                    "sub": user_id,
                    "iat": issued_at,
                    "jti": jti,
                    "iss": meta.get("iss"),
                    "aud": meta.get("aud"),
                    "oauth_client_id": oauth_client_id,
                },
            )

        # 2) OAuth opaque access token — fallback for non-JWT tokens
        #    (used if the OAuth /token endpoint issues opaque tokens instead of JWTs)
        try:
            pool = await _get_pool()
            row = await pool.fetchrow(
                """SELECT t.user_id, t.scopes, t.created_at, u.tokens_revoked_at
                     FROM oauth_access_tokens t
                     JOIN users u ON u.id = t.user_id
                    WHERE t.token = $1 AND t.expires_at > NOW()""",
                token,
            )
        except Exception:
            return None
        if row:
            revoked_at = row["tokens_revoked_at"]
            if revoked_at is not None and row["created_at"] <= revoked_at:
                return None
            return AccessToken(
                token=token,
                client_id=str(row["user_id"]),
                scopes=row["scopes"] if isinstance(row["scopes"], list) else ["user"],
                resource=settings.mcp_resource_url,
                subject=str(row["user_id"]),
                claims={"sub": str(row["user_id"])},
            )
        return None


# ── FastMCP server ──────────────────────────────────────────────────────────────

auth = RemoteAuthProvider(
    # S09 client tokens carry granular scopes, not the legacy full-access
    # "user" scope. Require authentication here; ScopeGate authorizes tools.
    token_verifier=ZyndTokenVerifier(required_scopes=[]),
    authorization_servers=[AnyHttpUrl(settings.public_base_url)],
    base_url=AnyHttpUrl(settings.mcp_origin),
    scopes_supported=["user", "memory:write", "cards:read", "cards:approve"],
    resource_name="ZYND",
)

_logo = Path(__file__).resolve().parent / "assets" / "zynd.png"
mcp = FastMCP(
    "zynd", auth=auth, instructions=_ZYND_INSTRUCTIONS,
    icons=[Icon(src=f"data:image/png;base64,{base64.b64encode(_logo.read_bytes()).decode('ascii')}",
                mime_type="image/png", sizes=["400x400"])],
)

# ── Skills ─────────────────────────────────────────────────────────────────────
# The connector ships basic memory skills (when/what to store) as MCP resources
# (skill://<name>/SKILL.md). Claude loads them alongside the connector; the same
# files are importable into ChatGPT Skills and Claude Code skill directories.
from pathlib import Path

from fastmcp.server.providers.skills import SkillsDirectoryProvider

_SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"
if _SKILLS_ROOT.is_dir():
    mcp.add_provider(SkillsDirectoryProvider(roots=[_SKILLS_ROOT]))


def _clip(text: str, limit: int = _MAX_REPORT_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit]


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
    text: str | None = None,
    uid: str = Depends(_uid),
) -> dict:
    """Save durable facts: typed fields at milestones, or ``text`` for one free-text fact.

    Use text alone or typed fields, never both. Do not save secrets or casual chatter.

    Prefer typed fields: tools → tools the user operates (not builds);
    languages/frameworks/skills → skills; projects → named ventures or
    products only; goals → intends. role and notes stay free text.
    Only include skills/languages/frameworks/tools the user EXPLICITLY
    stated; never infer a stack from a single "working on X" mention.
    Bad: tools=["webpack", "lodash", "jest", "eslint", "react"] copied from the
    repo's package.json. Good: tools=["Cursor"] after the user said "I use Cursor".
    The repo's dependencies are the project's, not the user's; at most 5
    technologies are kept per call.
    Never pass secrets, API keys, passwords, tokens, .env, repo paths, or
    one-off task details. Facts stay private until the user reviews them."""
    text = (text or "").strip()
    typed_values = [role, *(skills or []), *(languages or []), *(frameworks or []),
                    *(tools or []), *(projects or []), goals, notes]
    if text and any(str(value).strip() for value in typed_values):
        return {"saved": False, "reason": "Use text alone or typed fields, not both"}
    if text:
        cleaned = clean_text(text).strip()
        if len(cleaned) < _REMEMBER_MIN_CHARS:
            return {"saved": False, "reason": f"too short — pass a full sentence (min {_REMEMBER_MIN_CHARS} chars)"}
        turn = Turn(role="user", content=cleaned, timestamp=datetime.now(timezone.utc))
        inserted, _ = await ingest_turns(
            await _get_pool(), await _get_arq(), uid, "claude", [turn],
            min_chars=_REMEMBER_MIN_CHARS,
        )
        if inserted == 0:
            return {"saved": False, "reason": "already remembered (duplicate)"}
        return {"saved": True, "note": "Saved. Facts are extracted in the background; recall with get_my_context in a few seconds."}

    from app.services.findability import (
        declare_for_review,
        under_daily_cap,
    )
    from app.services.quality import (
        assess,
        assess_typed_field,
        log_observe,
    )

    pool = await _get_pool()
    typed_on = settings.feature_s05_typed_capture
    observe = settings.feature_s05_observe or typed_on
    if settings.feature_fact_families:
        # Each technology once, whichever field the agent put it under.
        from app.services.facts import dedupe_tech_fields
        languages, frameworks, skills, tools = dedupe_tech_fields(languages, frameworks, skills, tools)
    tech_note: str | None = None
    if settings.feature_strict_tech:
        from app.services.facts import MAX_TECH_VALUES, cap_tech_values
        languages, frameworks, skills, tools, dropped = cap_tech_values(languages, frameworks, skills, tools)
        if dropped:
            tech_note = (f"Kept the first {MAX_TECH_VALUES} technologies and ignored {dropped} more. "
                         "Send only what the user said they use or know, not the stack of the repo you are in.")

    typed_saved = 0
    typed_skipped = 0
    typed_fields: list[tuple[str, list[str] | None, str]] = [
        ("tools", tools, "uses_tool"),
        ("languages", languages, "has_skill"),
        ("frameworks", frameworks, "has_skill"),
        ("skills", skills, "has_skill"),
        ("projects", projects, "is_building"),
    ]

    if typed_on or observe:
        if typed_on and not await under_daily_cap(pool, uid):
            return {
                "saved": False,
                "reason": "daily report cap reached — try again tomorrow",
            }
        # One report must not flood the review inbox: cap values per field and
        # in total, so an agent inferring a whole stack from one sentence
        # cannot fill the queue in a single call.
        for field, values, predicate in typed_fields:
            for result in assess_typed_field(field, (values or [])[:MAX_PER_FIELD], predicate=predicate):
                if observe and not typed_on:
                    log_observe(uid, field, result)
                    continue
                if result.drop:
                    log_observe(uid, field, result)
                    typed_skipped += 1
                    continue
                if result.group == "noise":
                    log_observe(uid, field, result)
                if typed_saved >= MAX_TYPED_TOTAL:
                    typed_skipped += 1
                    continue
                # Soft triage: store look/noise so the owner can dismiss; hard-drop only.
                ok = await declare_for_review(
                    pool, uid, result.suggested_predicate or predicate, result.value,
                )
                if ok:
                    typed_saved += 1
                else:
                    typed_skipped += 1

        # goals is a string — split lightly into clauses when typed.
        if goals_text := _clip(goals, 600):
            for chunk in re.split(r"[;\n]+", goals_text):
                result = assess(chunk, intended_predicate="intends_to", field="goals")
                if not result.value:
                    continue
                if observe and not typed_on:
                    log_observe(uid, "goals", result)
                    continue
                if result.drop:
                    typed_skipped += 1
                    continue
                ok = await declare_for_review(
                    pool, uid, result.suggested_predicate or "intends_to", result.value,
                )
                if ok:
                    typed_saved += 1
                else:
                    typed_skipped += 1

    # role + notes (and legacy text path when typed capture is off) use extraction.
    lines: list[str] = []
    if role_text := _clip(role, 200):
        lines.append(f"The user's role: {role_text}")
    for line in (notes or "").splitlines():
        line = _clip(line)
        if line:
            lines.append(line)

    if not typed_on:
        for label, values in (("skill", skills), ("programming language", languages),
                              ("framework", frameworks), ("tool", tools)):
            for value in values or []:
                value = _clip(value, 120)
                if value:
                    lines.append(f"The user has a {label}: {value}")
        for project in projects or []:
            project = _clip(project, 240)
            if project:
                lines.append(f"The user works on the project: {project}")
        if goals_text := _clip(goals, 600):
            lines.append(f"The user's goal: {goals_text}")

    text_saved = 0
    text_skipped = 0
    if lines:
        stamp = datetime.now(timezone.utc)
        turns = [
            Turn(role="user", content=clean_text(line).strip(), timestamp=stamp)
            for line in lines
            if len(clean_text(line).strip()) >= _REMEMBER_MIN_CHARS
        ]
        if turns:
            inserted, skipped = await ingest_turns(
                pool, await _get_arq(), uid, _CARDS_SOURCE, turns,
                min_chars=_REMEMBER_MIN_CHARS,
            )
            text_saved = inserted
            text_skipped = skipped

    total_saved = typed_saved + text_saved
    total_skipped = typed_skipped + text_skipped
    if total_saved == 0:
        result = {
            "saved": False,
            "reason": "nothing new (too short, duplicates, or filtered)",
            "items_skipped": total_skipped,
        }
        if tech_note:
            result["tech_note"] = tech_note
        return result
    result = {
        "saved": True,
        "note": "Saved privately. The user reviews facts before anything becomes public.",
        "items_saved": total_saved,
        "items_skipped": total_skipped,
    }
    if tech_note:
        result["tech_note"] = tech_note
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def get_my_context(topic: str | None = None, k: int = 20,
                         uid: str = Depends(_uid),
                         token: AccessToken = CurrentAccessToken()) -> dict:
    """Load identity, profile, socials, brief, private facts, and approved public card.

    Call at conversation start, then again with ``topic`` whenever the conversation has
    a subject (a project, a technology, a person, a goal): without a topic you get what
    is true now; with one you also get older facts that relate to it. Facts with
    ``stale: true`` are past context, not current. topic filters facts only and k is
    bounded to 1..50.
    Present lists substantive sections, not proof of a complete memory graph.
    Optional unavailable sections are null; owner status/activity require cards:read
    or legacy user scope. A persona name may self-heal an empty stored display name.
    Show facts' statement text rather than internal predicates or confidence.
    """
    pool = await _get_pool()
    self_context = await load_self_context(pool, uid)
    k = max(1, min(k, 50))
    facts = await (context_slice(pool, uid, topic.strip(), k)
                   if topic and topic.strip() else active_context(pool, uid, k))
    card = await get_card(pool, uid)
    brief = await read_brief(self_context["supabase_user_id"] or uid)
    profile = normalize_profile(self_context["persona_status"]) if self_context["persona_status"] else None
    packet = {
        "identity": self_context["identity"],
        "profile": profile,
        "socials": self_context["socials"],
        "brief": brief or None,
        "facts": facts,
        "card": card,
        "present": ["identity"],
    }
    def substantive(item) -> bool:
        if isinstance(item, dict):
            return any(substantive(v) for v in item.values())
        if isinstance(item, list):
            return any(substantive(v) for v in item)
        return bool(item.strip()) if isinstance(item, str) else bool(item)

    for key in ("profile", "socials", "brief", "facts", "card"):
        if substantive(packet[key]):
            packet["present"].append(key)
    scopes = set(token.scopes or []) if token else set()
    if "user" in scopes or "cards:read" in scopes:
        from app.tools.card_status import get_owner_status
        try:
            result = await get_owner_status(pool, uid)
        except Exception:
            result = {"ok": False}
        if result.get("ok") and result.get("data"):
            packet["status"] = result["data"]
            packet["activity"] = result["data"].get("activity") or {}
        else:
            packet["status"] = None
            packet["activity"] = None
        if packet["status"]:
            packet["present"].append("status")
        if packet["activity"]:
            packet["present"].append("activity")
    return packet


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def export_my_context(uid: str = Depends(_uid)) -> dict:
    """Export the full active context graph as JSON-LD. Use when the user asks to
    export, download, back up, or inspect their complete ZYND profile."""
    return await build_jsonld_export(await _get_pool(), uid)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_similar_users(cluster_type: str = "intent_cluster", k: int = 10, uid: str = Depends(_uid)) -> list[dict]:
    """Find people with overlapping context. Use when the user asks for people
    like them, similar users, or people building/learning/working on similar
    things. cluster_type: intent_cluster, skill_cluster, belief_cluster,
    concept_cluster, full_context."""
    return await match_users(await _get_pool(), uid, cluster_type, max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def find_people(
    target: str,
    k: int = 10,
    sources: str = "all",
    group_id: str = "",
    uid: str = Depends(_uid),
) -> dict:
    """Find people matching a TARGET PROFILE — complementary people, not people
    like the user. Use when the user asks for investors, cofounders, designers,
    engineers, marketers, mentors, customers, domain experts, etc. Pass
    target="like_me" for people close to the user's own profile.

    Cards is the people index. Each result is one person:
      handle, name, headline, location, why (why they matched), sources, claimed,
      score, match_quality (exact | close | loose), url, and next_action:
        connect          — a claimed Card: call request_card_connection(target_handle=handle)
        invite_to_claim  — no claimed Card yet: call invite_to_claim(invite_ref=...) (only offered when enabled)
        view_profile     — nothing to act on; url is their public page or LinkedIn
    When the response has a `note` saying nothing matched exactly, call the people "the closest
    matches" and say what differs (match_quality and `relaxed` show it); never present a loose
    match as an exact one.
    LinkedIn people are searched only when too few strong matches were found (or when sources
    names "quickenrich"). Contact details are never in results; they are shared once a
    connection is accepted.

    Pass a natural-language target description (e.g. "seed-stage investor who
    backs dev-tools in India"). To find one specific person, pass their name, and their
    company if known ("Chandan Kumar", "Priya from Stripe", or a Card @handle). Without a
    company a name can only be looked up among Zynd Cards: if warnings contain
    name_needs_company, ask the user which company they work at and search again with it.
    When a person's `relaxed` list is present, the search had too few exact matches and
    loosened that filter (location, role, skills) to include them: call these "closest
    matches", not matches, and say what was loosened. A `note` in the result is meant for
    the user. sources is "all" unless the user explicitly restricts it
    to "cards", "zynd" and/or "quickenrich". A source that failed, or is not configured,
    is listed in warnings; the others are still returned.

    Pass group_id (from list_card_groups) to search only that group's members, e.g. an event
    or community; nothing outside the group is searched. Results already respect the user's
    match controls (see tune_matches): hidden people and muted topics are left out. Each person
    carries `verified` (identities proven, e.g. "linkedin") and `why`, which says how current an
    approved fact is."""
    wanted, explicit = people_search.requested_sources(sources)
    return await people_search.find(
        await _get_pool(), uid, target, limit=max(1, min(k, 20)), wanted=wanted, explicit=explicit,
        group_id=(group_id or "").strip())


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def confirm_fact_tool(predicate: str, object: str, uid: str = Depends(_uid)) -> dict:
    """Confirm an existing ZYND fact is correct. Use when the user confirms
    something ZYND remembers about them. Pass the exact predicate and object
    as returned by get_my_context. If the result has confirmed:false, retry
    with an exact predicate/object from the returned `matches`; never report
    success on a false result."""
    pool = await _get_pool()
    result = await confirm_fact(pool, uid, predicate, object)
    if result is None:
        return {
            "confirmed": False,
            "reason": f"no active fact matches predicate={predicate!r} object={object!r}",
            "matches": await near_matches(pool, uid, predicate, object),
        }
    return {"confirmed": True, **result}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
async def forget_fact_tool(predicate: str, object: str, uid: str = Depends(_uid)) -> dict:
    """Remove a ZYND fact. Use when the user says something ZYND remembers is
    wrong, outdated, private, should be removed, or should be forgotten.
    Pass the exact predicate and object as returned by get_my_context. If the
    result has forgotten:false, retry with an exact predicate/object from the
    returned `matches`; never report success on a false result."""
    pool = await _get_pool()
    result = await forget_fact(pool, uid, predicate, object)
    if result is None:
        return {
            "forgotten": False,
            "reason": f"no active fact matches predicate={predicate!r} object={object!r}",
            "matches": await near_matches(pool, uid, predicate, object),
        }
    await card_sync.notify_cards_refresh(pool, uid)
    return {"forgotten": True, **result}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def publish_page(content: str, title: str = "", format: str = "html",
                       visibility: str = "unlisted", uid: str = Depends(_uid)) -> dict:
    """Host an HTML or Markdown page and return a live public URL. Use this
    whenever the user asks to host, deploy, share, or publish any HTML or
    content — e.g. "host this", "make it live", "give me a link", "deploy
    this HTML", "publish this page". Do NOT create a local file when hosting
    is the goal — this tool IS the hosting. Pass the full content as `content`;
    set `format` to "html" or "markdown". Returns {success, url, slug, title}.
    Always show the `url` to the user after calling this.

    Requires a signed-in ZYND token. Pages are permanent for that user."""
    from app.services import pages_agent

    row = await (await _get_pool()).fetchrow("SELECT supabase_user_id FROM users WHERE id = $1", uid)
    suid = row["supabase_user_id"] if (row and row["supabase_user_id"]) else uid
    return await pages_agent.create_page(suid, content, title, format, visibility)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def list_my_pages(uid: str = Depends(_uid)) -> list[dict]:
    """List hosted shareable pages, newest first. Use when the user asks to
    see pages they have published. Requires a signed-in ZYND token."""
    from app.services import pages_agent
    row = await (await _get_pool()).fetchrow("SELECT supabase_user_id FROM users WHERE id = $1", uid)
    suid = row["supabase_user_id"] if (row and row["supabase_user_id"]) else uid
    return await pages_agent.list_pages(suid)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def disconnect(uid: str = Depends(_uid)) -> dict:
    """Sign out of ZYND — revoke all ZYND tokens (web, GPT, MCP clients).
    The user will need to reconnect to use ZYND again."""
    from app.services.sessions import revoke_user_tokens
    await revoke_user_tokens(await _get_pool(), uid)
    return {"status": "signed_out", "note": "Reconnect ZYND to sign back in."}


async def _social(op, uid: str, *args) -> dict:
    """Legacy social-link helper retained for non-MCP Python callers."""
    from app.services.social import SocialDisabled
    from app.services.persona import PersonaError
    try:
        result = await op(await _get_pool(), uid, *args)
        return {"ok": True, "result": result}
    except SocialDisabled as exc:
        return {"ok": False, "reason": str(exc), "hint": "persona connect/message is coming soon"}
    except (ValueError, PersonaError) as exc:
        return {"ok": False, "reason": str(exc)}


async def set_social_links(linkedin: str = "", instagram: str = "", x: str = "", github: str = "",
                           uid: str = Depends(_uid)) -> dict:
    from app.services import social
    return await _social(social.set_social, uid, {"linkedin": linkedin, "instagram": instagram, "twitter": x, "github": github})


# ── Cards-native Network Tools ───────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def list_card_connections(uid: str = Depends(_uid)) -> dict:
    """List Cards-native pending and accepted connections."""
    return await cards_network_tools.connections(await _get_pool(), uid)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def request_card_connection(target_handle: str, message: str = "",
                                  uid: str = Depends(_uid)) -> dict:
    """Send a connection request to a claimed, published Card by handle."""
    return await cards_network_tools.request_connection(await _get_pool(), uid, target_handle, message)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def invite_to_claim(invite_ref: str, message: str = "", uid: str = Depends(_uid)) -> dict:
    """Invite someone who has no claimed Card yet. Pass the `invite_ref` from a find_people result
    whose next_action is "invite_to_claim" (nothing else is accepted). This prepares their Card,
    which they claim by signing in with the same LinkedIn account, and queues your connection
    request for when they do. It does NOT contact them: give the user the returned claim_url /
    share_text to send. Tell the user the Card is prepared from their public LinkedIn name and
    headline only."""
    if not settings.feature_invite_to_claim:
        return {"ok": False, "error": "Invitations are not enabled"}
    from app.services import invite_refs
    person = invite_refs.verify(uid, invite_ref)
    if person is None:
        return {"ok": False, "error": "Unknown or expired invite_ref: run find_people again and use its invite_ref"}
    return await cards_network_tools.create_invite(
        await _get_pool(), uid, person["linkedin_url"], person["name"], person["headline"], _clip(message, 500))


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def saved_searches(action: str = "list", q: str = "", role: str = "", location: str = "",
                         skills: str = "", label: str = "", search_id: str = "",
                         uid: str = Depends(_uid)) -> dict:
    """Saved people searches: get notified when a NEW matching Card appears.
    action "add" saves a search (q, role, location, skills; label is a short name) — what already
    matches is not reported, only new people; "list" shows them; "remove" stops one (search_id).
    New matches show up as notes on the user's Cards home and in their notification email."""
    pool = await _get_pool()
    if action == "add":
        return await cards_network_tools.add_saved_search(pool, uid, _clip(q, 200), _clip(role, 100),
                                                          _clip(location, 100), _clip(skills, 200), _clip(label, 80))
    if action == "remove":
        return await cards_network_tools.remove_saved_search(pool, uid, search_id.strip())
    return await cards_network_tools.saved_searches(pool, uid)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def tune_matches(action: str, value: str = "", uid: str = Depends(_uid)) -> dict:
    """Tune who find_people shows the user. action: "hide_person" (value = Card handle: never show
    them again), "mute_topic" (value = a topic to leave out, e.g. "crypto trading"), "less_like_this"
    (value = a Card handle: rank people like them lower), "undo_hide_person" / "undo_mute_topic" /
    "undo_less_like_this" to reverse one, or "show" to list the current controls."""
    pool = await _get_pool()
    if action == "show":
        return await cards_network_tools.preferences(pool, uid)
    undo = action.startswith("undo_")
    kind = action.removeprefix("undo_")
    if kind not in ("hide_person", "mute_topic", "less_like_this"):
        return {"ok": False, "error": "action must be hide_person, mute_topic, less_like_this, an undo_ of those, or show"}
    return await cards_network_tools.change_preference(pool, uid, kind, _clip(value, 100), remove=undo)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
async def report_or_block_card(handle: str, action: str = "report", reason: str = "other",
                               details: str = "", uid: str = Depends(_uid)) -> dict:
    """Report or block a Card. action "report" (reason: spam, impersonation, harassment, inaccurate
    or other; details optional) sends it to a person for review and changes nothing automatically.
    action "block" ends any connection with them, stops them contacting the user, and hides them from
    searches. Only do this when the user asks; blocking cannot be undone from here."""
    pool = await _get_pool()
    if action == "block":
        return await cards_network_tools.block_card(pool, uid, handle.strip().lstrip("@"))
    return await cards_network_tools.report_card(pool, uid, handle.strip().lstrip("@"), reason, _clip(details, 1000))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def connection_brief(connection_id: str, uid: str = Depends(_uid)) -> dict:
    """For an ACCEPTED connection: what each person is working on now, what they have in common and
    a few things to bring up, from what both approved onto their Cards. Use before the user writes
    to someone they are connected with."""
    return await cards_network_tools.brief(await _get_pool(), uid, connection_id)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def respond_card_connection(connection_id: str, action: str,
                                  uid: str = Depends(_uid)) -> dict:
    """Accept, decline, block, or revoke a Cards-native connection."""
    return await cards_network_tools.respond_connection(await _get_pool(), uid, connection_id, action)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def read_card_dm(connection_id: str, limit: int = 100,
                       uid: str = Depends(_uid)) -> dict:
    """Read messages on an accepted Cards connection."""
    return await cards_network_tools.read_dm(await _get_pool(), uid, connection_id, limit)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def send_card_dm(connection_id: str, content: str,
                       uid: str = Depends(_uid)) -> dict:
    """Send a DM on an accepted Cards connection."""
    return await cards_network_tools.send_dm(await _get_pool(), uid, connection_id, content)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def list_card_groups(uid: str = Depends(_uid)) -> dict:
    """List Cards-native groups the authenticated user belongs to."""
    return await cards_network_tools.groups(await _get_pool(), uid)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def create_card_group(name: str, description: str = "", visibility: str = "private",
                            uid: str = Depends(_uid)) -> dict:
    """Create a Cards-native group."""
    return await cards_network_tools.create_group(await _get_pool(), uid, name, description, visibility)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_card_group_people(group_id: str, query: str = "",
                                 uid: str = Depends(_uid)) -> dict:
    """Find accepted Card connections eligible for a group invitation."""
    return await cards_network_tools.group_people(await _get_pool(), uid, group_id, query)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def invite_card_group_member(group_id: str, target_handle: str, message: str = "",
                                   uid: str = Depends(_uid)) -> dict:
    """Invite a connected Card to a group; the invitee must accept."""
    return await cards_network_tools.invite_group(await _get_pool(), uid, group_id, target_handle, message)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def list_card_group_invitations(uid: str = Depends(_uid)) -> dict:
    """List incoming Cards-native group invitations."""
    return await cards_network_tools.incoming_invites(await _get_pool(), uid)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def respond_card_group_invitation(invitation_id: str, decision: str,
                                        uid: str = Depends(_uid)) -> dict:
    """Accept or decline a Cards-native group invitation."""
    return await cards_network_tools.respond_invite(await _get_pool(), uid, invitation_id, decision)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def read_card_group_messages(group_id: str, limit: int = 100,
                                   uid: str = Depends(_uid)) -> dict:
    """Read messages from a Cards-native group."""
    return await cards_network_tools.group_messages(await _get_pool(), uid, group_id, limit)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def send_card_group_message(group_id: str, content: str,
                                  uid: str = Depends(_uid)) -> dict:
    """Post a message to a Cards-native group."""
    return await cards_network_tools.send_group_message(await _get_pool(), uid, group_id, content)


# ── Zynd Services Tools ────────────────────────────────────────────────────────

async def search_zynd_services(query: str, top_k: int = 5, category: str = "") -> dict:
    return await zynd_services_tools.search_zynd_services(query, top_k, category)


async def get_zynd_service_card(entity_id: str) -> dict:
    return await zynd_services_tools.get_zynd_service_card(entity_id)


async def call_zynd_service(entity_id: str, text: str = "", data: dict | None = None,
                             uid: str = Depends(_uid)) -> dict:
    return await zynd_services_tools.call_zynd_service(entity_id, text, data, uid)


# ── Brief & Todo Tools ─────────────────────────────────────────────────────────

async def append_to_my_brief(text: str, suid: str = Depends(_suid)) -> dict:
    return await brief_tools.append_to_my_brief(suid, text)


async def replace_my_brief(content: str, suid: str = Depends(_suid)) -> dict:
    return await brief_tools.replace_my_brief(suid, content)


async def clear_my_brief(suid: str = Depends(_suid)) -> dict:
    return await brief_tools.clear_my_brief(suid)


async def add_todo(title: str, suid: str = Depends(_suid)) -> dict:
    return await brief_tools.add_todo(suid, title)


# ── ASGI app ────────────────────────────────────────────────────────────────────
# Personal MCP stays auth'd at /mcp. When FEATURE_S11_PUBLIC_MCP is on, a second
# FastMCP (no auth) is merged at /cards-public-mcp in the same process.
# uvicorn app.mcp_http:app --host 0.0.0.0 --port 8090

if settings.feature_s09_mcp_clients:
    from app.mcp_owner import register as register_owner_tools
    from app.services.mcp_gate import ScopeGate

    register_owner_tools(mcp, _uid)
    mcp.add_middleware(ScopeGate())

_allowed_hosts = [
    h for h in (urlsplit(settings.mcp_public_base_url).hostname, "localhost", "127.0.0.1") if h
]

_auth_app = mcp.http_app(
    path="/mcp",
    stateless_http=not settings.feature_stateful_mcp,
    allowed_hosts=_allowed_hosts,
)

if settings.feature_s11_public_mcp:
    from contextlib import AsyncExitStack, asynccontextmanager

    from starlette.applications import Starlette
    from starlette.middleware import Middleware

    from app.cards_public_mcp import RateLimitMiddleware
    from app.cards_public_mcp import build_http_app as _build_public_mcp

    _public_app = _build_public_mcp(allowed_hosts=_allowed_hosts)

    @asynccontextmanager
    async def _combined_lifespan(app):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(_auth_app.lifespan(app))
            await stack.enter_async_context(_public_app.lifespan(app))
            yield

    # Merge routes (public first). Both FastMCP lifespans must run on the parent.
    # _auth_app's middleware must carry over too: AuthenticationMiddleware
    # (BearerAuthBackend → ZyndTokenVerifier) populates scope["user"], which the
    # /mcp route's RequireAuthMiddleware needs. Starlette drops app-level
    # middleware when only routes are merged, so without this every
    # authenticated POST /mcp 401s as invalid_token before the verifier runs.
    app = Starlette(
        routes=list(_public_app.routes) + list(_auth_app.routes),
        lifespan=_combined_lifespan,
        middleware=list(_auth_app.user_middleware) + [Middleware(RateLimitMiddleware)],
    )
else:
    app = _auth_app
