import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.agents import router as agents_router
from api.cards import router as cards_router
from api.health import router as health_router
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
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Zynd Cards API", version="1.0.0", lifespan=lifespan)

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
app.include_router(agents_router, prefix="/v1/agents", tags=["Agents"])
app.include_router(chat_router, prefix="/v1/chat", tags=["Chat"])
app.include_router(health_router, prefix="/health", tags=["Health"])
