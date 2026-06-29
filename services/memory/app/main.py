import hmac
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.auth import issue_personal_token, verify_access_token
from app.config import settings
from app.db import close_pool, get_pool, init_pool
from app.models import AssertionView, ContextRequest, DeclareRequest, FactRef, IngestRequest, IngestResponse
from app.services.ingest import ingest_turns
from app.connect import router as connect_router
from app.docs import router as docs_router
from app.oauth import router as oauth_router


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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(oauth_router)
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
        return verify_access_token(token)
    except ValueError:
        pass
    if settings.enable_dev_bearer and hmac.compare_digest(token, settings.dev_bearer_token):
        return app.state.dev_user_id
    raise HTTPException(status_code=401, detail="invalid bearer token")


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
    return [AssertionView(**dict(row)) for row in rows]


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
