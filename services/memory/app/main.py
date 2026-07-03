import hmac
import json
import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.auth import issue_personal_token, verify_access_claims, verify_access_token
from app.config import settings
from app.db import close_pool, get_pool, init_pool
from app.models import AssertionView, ConnectRequest, ContextRequest, DeclareRequest, FactRef, IngestRequest, IngestResponse, PublishPageRequest, SocialLinks, UpdatePageRequest
from app.services.ingest import ingest_turns
from app.connect import router as connect_router
from app.docs import router as docs_router
from app.oauth import router as oauth_router
from app.oauth import _well_known_router as oauth_well_known_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.dev_user_id = await _ensure_dev_user()
    yield
    await app.state.arq.aclose()
    await close_pool()


app = FastAPI(title="ZYND", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(oauth_router)
app.include_router(oauth_well_known_router)
app.include_router(connect_router)
app.include_router(docs_router)

_PRIVACY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZYND — Privacy Policy</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    max-width:720px;margin:48px auto;padding:0 20px;line-height:1.6;color:#222}
  h1{font-size:26px} h2{font-size:18px;margin-top:28px} a{color:#5b46e0}
  .muted{color:#666;font-size:14px}
</style></head>
<body>
  <h1>ZYND Privacy Policy</h1>
  <p class="muted">Last updated: 2026-06-26</p>

  <p>ZYND turns the messages you choose to send into a private, evolving context
  graph that you own. This policy explains what we collect and how we handle it.</p>

  <h2>What we collect</h2>
  <ul>
    <li><b>Your messages</b> — only the user-turn text you send through the ZYND
      connection. We do not collect the AI assistant's replies.</li>
    <li><b>Your email</b> — used to identify your account.</li>
  </ul>

  <h2>How we use it</h2>
  <p>We extract structured facts (what you're building, learning, intending) to
  build your context graph, and to surface relevant context to AI tools you
  authorize. We do not sell your data or use it for advertising.</p>

  <h2>Storage &amp; retention</h2>
  <p>Data is stored in our database. Facts decay over time and inactive raw
  messages are pruned on a rolling retention window.</p>

  <h2>Your control</h2>
  <p>You can disconnect ZYND from ChatGPT at any time. You may request deletion of
  your data by contacting us; account deletion removes your facts and raw messages.</p>

  <h2>Contact</h2>
  <p>Questions or deletion requests: <a href="mailto:privacy@zynd.ai">privacy@zynd.ai</a></p>
</body></html>"""


async def _ensure_dev_user() -> str:
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO users (email, display_name)
           VALUES ($1, 'Dev User')
           ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
           RETURNING id""",
        settings.dev_user_email,
    )
    return str(row["id"])


async def current_user(authorization: str = Header(default="")) -> str:
    """Resolve the caller's user_id from the bearer token.

    Two accepted tokens: the per-user OAuth JWT (M2, what ChatGPT sends) and the
    shared dev token (local testing only). JWT is tried first.
    """
    scheme, _, value = authorization.partition(" ")  # RFC 6750: scheme is case-insensitive
    token = value.strip() if scheme.lower() == "bearer" else ""
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        user_id, issued_at = verify_access_claims(token)
    except ValueError:
        if settings.enable_dev_bearer and hmac.compare_digest(token, settings.dev_bearer_token):
            return app.state.dev_user_id   # dev backdoor: not a JWT, no revocation check
        raise HTTPException(status_code=401, detail="invalid bearer token")
    from app.services.sessions import tokens_revoked
    if await tokens_revoked(get_pool(), user_id, issued_at):
        raise HTTPException(status_code=401, detail="session was signed out — please sign in again")
    return user_id


@app.get("/health")
async def health() -> dict:
    await get_pool().execute("SELECT 1")
    return {"status": "ok"}


@app.get("/.well-known/openapi.json", include_in_schema=False)
async def action_schema() -> dict:
    """OpenAPI schema to import into the Custom GPT builder."""
    from app.action_schema import build_action_schema
    return build_action_schema()


@app.get("/privacy", include_in_schema=False)
async def privacy() -> HTMLResponse:
    """Privacy policy — required to publish the ChatGPT GPT publicly."""
    return HTMLResponse(_PRIVACY_HTML)


@app.post("/token/exchange")
async def token_exchange(authorization: str = Header(default="")) -> dict:
    """Exchange a Supabase (Google) access token for a ZYND personal token.

    Called by the dashboard after Google sign-in. Identity is verified by Supabase,
    so creating the user password-less here is safe (not an unauthenticated form)."""
    supabase_token = authorization.removeprefix("Bearer ").strip()
    from app.supabase_auth import supabase_identity
    identity = await supabase_identity(supabase_token)
    if not identity:
        raise HTTPException(status_code=401, detail="invalid or expired Google session")
    email, display_name, sub = identity

    user_id = await get_pool().fetchval(
        """INSERT INTO users (email, display_name, supabase_user_id) VALUES ($1, $2, $3)
           ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name,
                 supabase_user_id = EXCLUDED.supabase_user_id RETURNING id""",
        email, display_name, sub,
    )
    from app.services.persona import link_user
    agent_id = await link_user(get_pool(), user_id, sub, display_name, email)  # gated; no-op unless persona_enabled
    if agent_id:  # persona resolved → seed their ZYND memory from the persona profile
        from app.services.persona_ingest import seed_persona_profile
        await seed_persona_profile(get_pool(), app.state.arq, user_id, sub)
    base = settings.public_base_url.rstrip("/")
    return {
        "token": issue_personal_token(str(user_id)),
        "mcp_url": f"{base}/mcp",
        "email": email,
    }


@app.post("/me/social-links")
async def set_my_social_links(body: SocialLinks, authorization: str = Header(default="")) -> dict:
    """Store the caller's public social links in memory-layer, synced from the persona
    You page. Authenticated with the persona Supabase session token (same as
    /token/exchange), so the persona webapp can push without a separate ZYND token."""
    supabase_token = authorization.removeprefix("Bearer ").strip()
    from app.supabase_auth import supabase_identity
    identity = await supabase_identity(supabase_token)
    if not identity:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    email, _display_name, _sub = identity
    links = {k: v.strip() for k, v in body.model_dump().items() if v and v.strip()}
    await get_pool().execute(
        "UPDATE users SET socials = $2::jsonb WHERE email = $1", email, json.dumps(links))
    return {"status": "saved", "socials": links}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, user_id: str = Depends(current_user)) -> IngestResponse:
    """Synchronous, must stay <200ms: auth + dedup + INSERT + enqueue only.
    Embedding/extraction happen in the worker (brief §7.2)."""
    inserted, skipped = await ingest_turns(
        get_pool(), app.state.arq, user_id, req.source_system, req.turns, req.conversation_id,
    )
    return IngestResponse(chunks_inserted=inserted, chunks_skipped=skipped)


async def _active_graph(user_id: str) -> list[AssertionView]:
    rows = await get_pool().fetch(
        """SELECT a.predicate, e.canonical_name AS object, e.entity_type AS object_type,
                  a.confidence, a.source_system, a.decay_fn, a.version, a.observed_at
             FROM assertions a
             LEFT JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL
            ORDER BY a.confidence DESC""",
        user_id,
    )
    from app.taxonomy import humanize
    return [
        AssertionView(statement=humanize(row["predicate"], row["object"]), **dict(row))
        for row in rows
    ]


@app.get("/me/graph", response_model=list[AssertionView])
async def my_graph(user_id: str = Depends(current_user)) -> list[AssertionView]:
    """The authenticated user's own active facts. The GPT calls this to answer
    'what do you know about me?'."""
    return await _active_graph(user_id)


@app.get("/users/{user_id}/graph", response_model=list[AssertionView])
async def get_graph(user_id: str, auth_user: str = Depends(current_user)) -> list[AssertionView]:
    if user_id != auth_user:
        raise HTTPException(status_code=403, detail="can only read your own graph")
    return await _active_graph(user_id)


@app.get("/me/matches")
async def my_matches(
    cluster_type: str = "intent_cluster",
    limit: int | None = None,
    user_id: str = Depends(current_user),
) -> list[dict]:
    """People most similar to the caller in a cluster (brief §6.1). The GPT/MCP
    calls this for 'who else is building/working on what I am?'."""
    from app.services.matching import match_users
    try:
        return await match_users(get_pool(), user_id, cluster_type, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/me/find-people")
async def my_find_people(
    target: str,
    limit: int | None = None,
    user_id: str = Depends(current_user),
) -> list[dict]:
    """People whose PUBLIC findability profile matches a described TARGET profile
    (complementary search). The GPT calls this for 'find me an X' (investor, hire,
    partner). Use /me/matches for 'who is like me'."""
    from app.services.matching import search_by_query
    try:
        return await search_by_query(get_pool(), user_id, target, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/me/connect")
async def my_connect(body: ConnectRequest, user_id: str = Depends(current_user)) -> dict:
    """Send a connection request to a matched person (target_user_id from findPeople/
    findMatches). Routed through persona (agent-to-agent), so it works even if the
    target is offline."""
    from app.services import social
    from app.services.persona import PersonaError
    from app.services.social import SocialDisabled
    try:
        result = await social.connect(get_pool(), user_id, body.target_user_id, body.message)
        return {"status": "request_sent", "result": result}
    except SocialDisabled as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, PersonaError) as exc:
        logging.getLogger("zynd.connect").warning(
            "connect %s -> %s failed: %s: %s", user_id, body.target_user_id, type(exc).__name__, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/me/logout")
async def my_logout(user_id: str = Depends(current_user)) -> dict:
    """Sign out everywhere: revoke all of the user's tokens (this access token, its
    refresh token, and any MCP token). The next request prompts a fresh sign-in."""
    from app.services.sessions import revoke_user_tokens
    await revoke_user_tokens(get_pool(), user_id)
    return {"status": "signed_out"}


@app.post("/me/confirm")
async def confirm_my_fact(ref: FactRef, user_id: str = Depends(current_user)) -> dict:
    """User confirms a fact → confidence 0.97, source=user_confirmed (brief §6)."""
    from app.services.control import confirm_fact
    ok = await confirm_fact(get_pool(), user_id, ref.predicate, ref.object)
    if not ok:
        raise HTTPException(status_code=404, detail="no active fact matches that predicate/object")
    return {"status": "confirmed", "predicate": ref.predicate, "object": ref.object}


@app.post("/me/forget")
async def forget_my_fact(ref: FactRef, user_id: str = Depends(current_user)) -> dict:
    """User forgets a fact → soft-deleted (valid_until set, never hard-deleted; §14.1)."""
    from app.services.control import forget_fact
    ok = await forget_fact(get_pool(), user_id, ref.predicate, ref.object)
    if not ok:
        raise HTTPException(status_code=404, detail="no active fact matches that predicate/object")
    return {"status": "forgotten", "predicate": ref.predicate, "object": ref.object}


@app.get("/match/{user_id}")
async def get_match(
    user_id: str,
    cluster_type: str = "intent_cluster",
    limit: int | None = None,
    auth_user: str = Depends(current_user),
) -> list[dict]:
    """Top-N users whose `cluster_type` vector is nearest to this user's."""
    if user_id != auth_user:
        raise HTTPException(status_code=403, detail="can only query your own matches")
    from app.services.matching import match_users
    try:
        return await match_users(get_pool(), user_id, cluster_type, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/me/findability")
async def my_findability_card(user_id: str = Depends(current_user)) -> list[dict]:
    """The user's public findability card — the only facts used for matching (v2)."""
    from app.services.findability import get_card
    return await get_card(get_pool(), user_id)


@app.get("/me/findability/suggestions")
async def my_findability_suggestions(user_id: str = Depends(current_user)) -> list[dict]:
    """Inferred findability-eligible facts not yet public — 'ZYND noticed this. Keep it?'."""
    from app.services.findability import get_suggestions
    return await get_suggestions(get_pool(), user_id)


@app.post("/me/findability/approve")
async def approve_findability(ref: FactRef, user_id: str = Depends(current_user)) -> dict:
    """Publish an inferred fact onto the card so it becomes matchable."""
    from app.services.findability import approve
    if not await approve(get_pool(), user_id, ref.predicate, ref.object):
        raise HTTPException(status_code=404, detail="no matching private findability fact")
    return {"status": "approved", "predicate": ref.predicate, "object": ref.object}


@app.post("/me/findability/revoke")
async def revoke_findability(ref: FactRef, user_id: str = Depends(current_user)) -> dict:
    """Take a fact off the public card (it stays in private memory)."""
    from app.services.findability import revoke
    if not await revoke(get_pool(), user_id, ref.predicate, ref.object):
        raise HTTPException(status_code=404, detail="no matching public fact")
    return {"status": "revoked", "predicate": ref.predicate, "object": ref.object}


@app.post("/me/findability/declare")
async def declare_findability(req: DeclareRequest, user_id: str = Depends(current_user)) -> dict:
    """User explicitly adds a public findability fact (building/learning/seeking/…)."""
    from app.services.findability import declare
    try:
        await declare(get_pool(), user_id, req.predicate, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "declared", "predicate": req.predicate, "value": req.value}


@app.get("/export/{user_id}")
async def export_context(user_id: str, auth_user: str = Depends(current_user)) -> dict:
    """Full active context as a portable JSON-LD packet (brief §11.1)."""
    if user_id != auth_user:
        raise HTTPException(status_code=403, detail="can only export your own context")
    from app.services.export import build_jsonld_export
    return await build_jsonld_export(get_pool(), user_id)


@app.post("/context/{user_id}")
async def context_packet(
    user_id: str, req: ContextRequest, auth_user: str = Depends(current_user)
) -> list[dict]:
    """Top-K assertions relevant to a topic — the MCP slice over HTTP (brief §11.2)."""
    if user_id != auth_user:
        raise HTTPException(status_code=403, detail="can only query your own context")
    from app.services.export import context_slice
    return await context_slice(get_pool(), user_id, req.topic, req.k)


# ── Shareable page hosting ──────────────────────────────────────────────
# The GPT/agent creates an HTML or Markdown artifact and hosts it at a public
# link (/pages/{slug}). Authed CRUD lives under /me/pages; the served page is
# public (unguessable slug).

@app.post("/me/pages")
async def publish_page(body: PublishPageRequest, user_id: str = Depends(current_user)) -> dict:
    """Host an HTML/Markdown page and return its public share URL."""
    from app.services import pages
    result = await pages.create_page(
        get_pool(), user_id, body.content, body.title, body.format, body.visibility
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "could not create page"))
    return result


@app.get("/me/pages")
async def list_my_pages(user_id: str = Depends(current_user)) -> list[dict]:
    """List the pages the user has hosted, newest first."""
    from app.services import pages
    return await pages.list_pages(get_pool(), user_id)


@app.patch("/me/pages/{slug}")
async def edit_page(slug: str, body: UpdatePageRequest, user_id: str = Depends(current_user)) -> dict:
    """Update one of the user's hosted pages (only provided fields change)."""
    from app.services import pages
    result = await pages.update_page(
        get_pool(), user_id, slug, body.content, body.title, body.format, body.visibility
    )
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "page not found"))
    return result


@app.delete("/me/pages/{slug}")
async def remove_page(slug: str, user_id: str = Depends(current_user)) -> dict:
    """Delete one of the user's hosted pages."""
    from app.services import pages
    result = await pages.delete_page(get_pool(), user_id, slug)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "page not found"))
    return result


_PAGE_404_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Page not found</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f8fa;
color:#55555f;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.b{text-align:center}.b h1{font-size:3rem;margin:0;color:#1a1a1e}</style></head>
<body><div class="b"><h1>404</h1><p>This page doesn't exist or is private.</p></div></body></html>"""


# Hosted pages contain user/GPT-authored HTML+JS. Serving it on the API origin
# is a stored-XSS surface, so we sandbox every page: the CSP `sandbox` directive
# forces a unique null origin, so page scripts still run but cannot make
# same-origin credentialed calls to the API, read its storage, or be framed for
# clickjacking. (api.zynd.ai sets no cookies, so this is defence-in-depth.)
_PAGE_SECURITY_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-forms",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@app.get("/pages/{slug}", include_in_schema=False)
async def serve_page(slug: str) -> HTMLResponse:
    """Publicly render a hosted page by slug (server-side). No auth."""
    from app.services import pages
    row = await pages.get_page_public(get_pool(), slug)
    if not row:
        return HTMLResponse(_PAGE_404_HTML, status_code=404, headers=_PAGE_SECURITY_HEADERS)
    return HTMLResponse(pages.render_page_html(row), headers=_PAGE_SECURITY_HEADERS)
