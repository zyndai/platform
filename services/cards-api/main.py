from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.agents import router as agents_router
from api.cards import router as cards_router
from api.health import router as health_router
from api.onboard import router as onboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


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
app.include_router(cards_router, prefix="/cards", tags=["Cards"])
app.include_router(agents_router, prefix="/v1/agents", tags=["Agents"])
app.include_router(health_router, prefix="/health", tags=["Health"])
