"""
Zynd AI Networking Agent — FastAPI Entry Point

Registers all routers and starts the application.
Run with:  uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config

# ── Routers ──────────────────────────────────────────────────────────
from api.auth import router as auth_router
from api.oauth_routes import router as oauth_router
from api.chat import router as chat_router
from api.connections import router as connections_router
from api.persona import router as persona_router
from api.telegram import router as telegram_router

# ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Zynd AI Networking Agent",
    version="0.1.0",
    description="Backend for the Zynd AI social networking agent platform.",
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
app.include_router(telegram_router, prefix="/api/telegram", tags=["Telegram"])

@app.get("/health")
async def health():
    from agent.zynd_core import get_zynd_agent
    zynd = get_zynd_agent()
    return {
        "status": "ok",
        "llm_provider": config.LLM_PROVIDER,
        "zynd_agent": {
            "running": zynd is not None,
            "agent_id": zynd.agent_id if zynd else None,
        },
    }


@app.on_event("startup")
async def _startup():
    """Start the global Zynd AI Agent."""
    
    if not config.ZYND_WEBHOOK_BASE_URL:
        print("[Zynd AI] Warning: ZYND_WEBHOOK_BASE_URL is not set. Webhooks will default to localhost and may not be reachable over the internet.")
        config.ZYND_WEBHOOK_BASE_URL = "http://localhost:8000"
        
    # Start the core server agent on port 5050
    from agent.zynd_core import start_zynd_agent
    result = start_zynd_agent()
    print(f"[Zynd AI] Core Agent startup: {result}")
