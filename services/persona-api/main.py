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
        "*",
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
    """Start the Zynd AI agent on the network at server boot."""
    from agent.zynd_core import start_zynd_agent
    result = start_zynd_agent()
    print(f"[Zynd AI] Agent startup: {result}")
