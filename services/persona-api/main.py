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
from api.persona import router as persona_router
from api.meetings import router as meetings_router
from api.telegram import router as telegram_router
from api.linkedin import router as linkedin_router
from api.approvals import router as approvals_router
from api.matches import router as matches_router
from api.brief import router as brief_router

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

    yield

    # ── Shutdown ──
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
app.include_router(persona_router, prefix="/api/persona", tags=["Persona"])
app.include_router(meetings_router, prefix="/api/meetings", tags=["Meetings"])
app.include_router(telegram_router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(linkedin_router, prefix="/api/linkedin", tags=["LinkedIn"])
app.include_router(approvals_router, prefix="/api/approvals", tags=["Approvals"])
app.include_router(matches_router, prefix="/api/matches", tags=["Matches"])
app.include_router(brief_router,   prefix="/api/brief",   tags=["Brief"])


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
