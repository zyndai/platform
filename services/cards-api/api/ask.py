"""Natural-language profile search for ChatGPT / browsing agents.

`GET /ask?q=...` and `POST /ask {"q": "..."}` both run semantic search over
published agent cards and return ranked profiles. Caddy routes `/ask*` here so
ChatGPT (and any browsing agent) can research Zynd — e.g. "find me a blockchain
dev" returns matching profiles with names, skills, match reasons and URLs.
"""
import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services import search as search_service

router = APIRouter()


class AskRequest(BaseModel):
    q: str


@router.get("")
async def ask_get(q: str = Query("", max_length=200), limit: int = Query(10, ge=1, le=50)):
    results = await asyncio.to_thread(
        search_service.search_agents, q, "", "", "", "", "", None, limit
    )
    return {"query": q, "results": results, "numberOfItems": len(results)}


@router.post("")
async def ask_post(body: AskRequest, limit: int = Query(10, ge=1, le=50)):
    results = await asyncio.to_thread(
        search_service.search_agents, body.q, "", "", "", "", "", None, limit
    )
    return {"query": body.q, "results": results, "numberOfItems": len(results)}
