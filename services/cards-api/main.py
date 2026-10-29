import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

import config
from api.agents import router as agents_router
from api.cards import router as cards_router
from api.companion import router as companion_router
from api.health import router as health_router
from api.mcp import router as mcp_router
from api.onboard import router as onboard_router
from api.ask import router as ask_router
from api.chat import router as chat_router
from api.internal import router as internal_router
from api.events import router as events_router
from api.owner_home import router as owner_home_router
from api.intros import router as intros_router
from api.visitors import router as visitors_router
from api.network import router as network_router
from api.feed import router as feed_router

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

    group_memory_task = None
    if config.FEATURE_GROUP_MEMORY:
        from services.group_agent import group_memory_loop
        group_memory_task = asyncio.create_task(group_memory_loop())
        logger.info("group memory worker started")
    from services import card_cache
    card_cache.warm()       # the first search after a deploy should not pay for reading every card

    group_agent_task = None
    if config.FEATURE_GROUP_AGENT_REPLIES:
        from services.group_agent import agent_reply_loop
        group_agent_task = asyncio.create_task(agent_reply_loop())
        logger.info("group agent reply worker started")

    yield
    for running in (task, memory_task, group_memory_task, group_agent_task):
        if running:
            running.cancel()
            try:
                await running
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Zynd Cards API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def owner_no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/cards/mine", "/cards/notifications", "/cards/companion", "/cards/feed","/internal/owner-status")) or "/intro" in request.url.path:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Authorization"
    return response

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
app.include_router(visitors_router, prefix="/cards", tags=["Visitor privacy"])
app.include_router(network_router, prefix="/cards", tags=["Cards network"])
app.include_router(feed_router, prefix="/cards", tags=["Feed"])
app.include_router(owner_home_router, prefix="/cards", tags=["Owner home"])
app.include_router(intros_router,prefix="/cards",tags=["Intros"])
app.include_router(companion_router, prefix="/cards/companion", tags=["Companion"])
app.include_router(cards_router, prefix="/cards", tags=["Cards"])
app.include_router(mcp_router, prefix="/cards", tags=["MCP connector"])
app.include_router(agents_router, prefix="/v1/agents", tags=["Agents"])
app.include_router(chat_router, prefix="/v1/chat", tags=["Chat"])
app.include_router(health_router, prefix="/health", tags=["Health"])
app.include_router(internal_router, prefix="/internal", tags=["Internal"])
app.include_router(events_router, tags=["Events"])

# Prometheus scrape endpoint for infra/observability: request counts and latency per
# route template. Paths that match no route (scanners) are grouped as "none", so label
# cardinality stays bounded. Caddy answers 404 for /metrics on every public host.
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)
