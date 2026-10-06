import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from api.agents import router as agents_router
from api.cards import router as cards_router
from api.health import router as health_router
from api.mcp import router as mcp_router
from api.onboard import router as onboard_router
from api.ask import router as ask_router
from api.chat import router as chat_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if config.APIFY_API_KEY and config.X_USER_ACCESS_TOKEN:
        from x.mentions import polling_loop
        task = asyncio.create_task(polling_loop())
        logger.info("X bot polling task started (Apify reads + X API writes)")
    else:
        logger.warning("X bot disabled — APIFY_API_KEY or X_USER_ACCESS_TOKEN not set")

    memory_task = None
    if config.MEMORY_SERVICE_TOKEN:
        from services.zynd_memory import memory_refresh_loop
        memory_task = asyncio.create_task(memory_refresh_loop())
        logger.info(
            "ZYND memory refresh loop started (every %dh)",
            config.MEMORY_REFRESH_INTERVAL_HOURS,
        )
    else:
        logger.warning("ZYND memory refresh disabled — MEMORY_SERVICE_TOKEN not set")
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if memory_task:
        memory_task.cancel()
        try:
            await memory_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Zynd Cards API", version="1.0.0", lifespan=lifespan)

# Registered before CORSMiddleware so CORS wraps it (the last middleware added
# runs first): the 503 then carries CORS headers and browsers show the message
# instead of a CORS error.
@app.middleware("http")
async def maintenance_readonly(request, call_next):
    if config.MAINTENANCE_READONLY and request.method in ("POST", "PATCH", "PUT", "DELETE"):
        return JSONResponse(
            status_code=503,
            content={"detail": "Cards is read-only for maintenance, back shortly"},
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        config.FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


app.include_router(onboard_router, prefix="/onboard", tags=["Onboard"])
app.include_router(ask_router, prefix="/ask", tags=["Ask"])
app.include_router(cards_router, prefix="/cards", tags=["Cards"])
app.include_router(mcp_router, prefix="/cards", tags=["MCP connector"])
app.include_router(agents_router, prefix="/v1/agents", tags=["Agents"])
app.include_router(chat_router, prefix="/v1/chat", tags=["Chat"])
app.include_router(health_router, prefix="/health", tags=["Health"])
