"""
Zynd AI Networking Agent — FastAPI Entry Point

Registers all routers and starts the application.
Run with:  uvicorn main:app --reload --port 8000
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import config

# ── Routers ──────────────────────────────────────────────────────────
from api.auth import router as auth_router
from api.oauth_routes import router as oauth_router
from api.chat import router as chat_router
from api.connections import router as connections_router
from api.people import router as people_router
from api.persona import router as persona_router
from agent.a2a_router import router as a2a_router
from api.meetings import router as meetings_router
from api.telegram import router as telegram_router
from api.linkedin import router as linkedin_router
from api.approvals import router as approvals_router
from api.matches import router as matches_router
from api.todos import router as todos_router
from api.memory import router as memory_router
from api.groups import router as groups_router
from api.services import router as services_router
from api.agents import router as agents_router
from api.pages import router as pages_router
from api.transcribe import router as transcribe_router

# ─────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the application."""

    # ── Startup ──
    if not config.ZYND_WEBHOOK_BASE_URL:
        print("[Zynd AI] Warning: ZYND_WEBHOOK_BASE_URL is not set.")
        config.ZYND_WEBHOOK_BASE_URL = "http://localhost:8000"

    # Rehydrate all active user personas and start heartbeats.
    # (The old global ZyndNetworkingAgent is retired — personas handle
    # all networking now. See agent/zynd_core.py for details.)
    from agent.persona_manager import startup as persona_startup
    await persona_startup()

    # A2A v3 lifecycle: reconcile orphan tasks (any 'working'/'submitted'
    # rows from a prior process get flipped to failed/server_restart),
    # then start the idle-TTL sweeper for interrupted tasks.
    from agent.a2a_router import start_a2a_lifecycle
    await start_a2a_lifecycle()

    # Wire the outbound-callback registrar into agent.a2a.transport.
    # Importing this module performs the wiring as a side effect — no
    # function call needed. Without this, push-mode dispatches degrade
    # to sync SEND because the dispatcher has no place to persist them.
    import services.callbacks  # noqa: F401

    # Watch each persona's Brief Google Doc for changes and extract
    # any new todo items the user added. Single async task; safe to
    # run alongside the heartbeat manager.
    from agent.brief_watcher import brief_watcher
    await brief_watcher.start()

    # Proactive agent — daily briefs, nudges, evening recaps.
    # Runs on a background cadence per active user. Safe to start
    # after personas are rehydrated (needs active user list).
    from agent.proactive_loop import get_proactive_agent
    await get_proactive_agent().start()

    # GitHub sync — refreshes connected users' repos/languages daily
    # and writes new knowledge to the memory layer.
    from agent.github_sync_loop import get_github_sync_loop
    await get_github_sync_loop().start()

    yield

    # ── Shutdown ──
    from agent.github_sync_loop import get_github_sync_loop as _ghs
    await _ghs().stop()
    from agent.proactive_loop import get_proactive_agent as _pa
    await _pa().stop()
    from agent.a2a_router import stop_a2a_lifecycle
    await stop_a2a_lifecycle()
    from agent.brief_watcher import brief_watcher as bw
    await bw.stop()
    from agent.persona_manager import shutdown as persona_shutdown
    await persona_shutdown()
    print("[Zynd AI] Graceful shutdown complete")


app = FastAPI(
    title="Zynd AI Networking Agent",
    version="2.0.0",
    description="Backend for the Zynd AI social networking agent platform.",
    lifespan=lifespan,
)

# ── CORS (allow Next.js frontend) ────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        config.FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
        "https://zyndpersona.shortblogs.org",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ── Mount routers ────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(oauth_router, prefix="/api/oauth", tags=["OAuth"])
app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
app.include_router(connections_router, prefix="/api/connections", tags=["Connections"])
app.include_router(people_router, prefix="/api/people", tags=["People"])
app.include_router(persona_router, prefix="/api/persona", tags=["Persona"])
# A2A v3 transport. Mounted at the same prefix as the persona router
# so the per-persona base URL `/api/persona/{user_id}` is the discoverable
# entity_url: peers fetch the signed card from
# /api/persona/{user_id}/.well-known/agent-card.json and dispatch
# signed JSON-RPC envelopes at /api/persona/{user_id}/a2a/v1.
app.include_router(a2a_router, prefix="/api/persona", tags=["A2A"])
app.include_router(meetings_router, prefix="/api/meetings", tags=["Meetings"])
app.include_router(telegram_router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(linkedin_router, prefix="/api/linkedin", tags=["LinkedIn"])
app.include_router(approvals_router, prefix="/api/approvals", tags=["Approvals"])
app.include_router(matches_router, prefix="/api/matches", tags=["Matches"])
app.include_router(todos_router, prefix="/api/todos", tags=["Todos"])
app.include_router(memory_router, prefix="/api/memory", tags=["Memory"])
app.include_router(groups_router, prefix="/api/groups", tags=["Groups"])
app.include_router(services_router, prefix="/api/services", tags=["Services"])
app.include_router(agents_router, prefix="/api/agents", tags=["Agents"])
app.include_router(pages_router, prefix="/api/pages", tags=["Pages"])
app.include_router(transcribe_router, prefix="/api/transcribe", tags=["Transcribe"])


# Temporary diagnostic endpoint — remove after debugging
@app.post("/test-json")
async def test_json(request: Request):
    """Raw JSON echo — tests if FastAPI can parse ANY POST body."""
    from fastapi import Request as Req
    body = await request.json()
    return {"received": body}


@app.get("/health")
async def health():
    from agent.heartbeat_manager import get_heartbeat_manager
    hb = get_heartbeat_manager()
    return {
        "status": "ok",
        "llm_provider": config.LLM_PROVIDER,
        "heartbeat": {
            "active_personas": hb.active_count,
        },
    }
