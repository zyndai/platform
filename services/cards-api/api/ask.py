"""Natural-language profile search for ChatGPT / browsing agents.

`GET /ask?q=...` and `POST /ask {"q": "..."}` both run semantic search over
published agent cards and return ranked profiles. Caddy routes `/ask*` here so
ChatGPT (and any browsing agent) can research Zynd — e.g. "find me a blockchain
dev" returns matching profiles with names, skills, match reasons and URLs.

Unclaimed (scraped, no owner) cards are excluded by default so agents only
ever surface people who opted in; pass `include_unclaimed=true` to search the
full directory (the website's own /find UI does).
"""
import asyncio

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

import config
from services import cards as cards_service
from services import events as events_service
from services import search as search_service

router = APIRouter()


class AskRequest(BaseModel):
    q: str


def _effective_include(include_unclaimed: bool) -> bool:
    # Feature flag off = old include-everyone behaviour (rollback path).
    return include_unclaimed or not config.FEATURE_S03_UNCLAIMED_TIERING


def _annotate_claimed(results: list[dict], *, keep_unclaimed: bool) -> list[dict]:
    """Add the claimed flag (never the email).

    Search SQL is supposed to drop unclaimed cards, but a database whose
    RPC predates that filter still returns them. Drop them here so /ask
    cannot leak a scraped card to agents.
    """
    claimed = cards_service.claimed_by_handles([r["handle"] for r in results if r.get("handle")])
    kept = []
    for r in results:
        if r.get("handle"):
            r["claimed"] = claimed.get(r["handle"], False)
        if keep_unclaimed or r.get("claimed") is True:
            kept.append(r)
    return kept


@router.get("")
async def ask_get(
    request: Request,
    q: str = Query("", max_length=200),
    limit: int = Query(10, ge=1, le=50),
    include_unclaimed: bool = Query(False),
    search_id: str = Query("", max_length=64),
    via: str = Query("", max_length=16),
):
    return await _ask(request, q, limit, include_unclaimed, search_id, via)


async def _ask(request: Request, q: str, limit: int, include_unclaimed: bool, search_id: str, via: str) -> dict:
    search_id, via = events_service.search_context(search_id, via, default="ask")
    keep_unclaimed = _effective_include(include_unclaimed)
    results = await asyncio.to_thread(
        search_service.search_agents, q, "", "", "", "", "", None, limit,
        keep_unclaimed,
    )
    events_service.emit("agent_fetch", request=request, meta={"endpoint": "ask"})
    results = _annotate_claimed(results, keep_unclaimed=keep_unclaimed)
    events_service.record_search(request, results, has_query=bool(q.strip()), search_id=search_id, via=via)
    return {"query": q, "search_id": search_id, "results": results, "numberOfItems": len(results)}


@router.post("")
async def ask_post(
    body: AskRequest,
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    include_unclaimed: bool = Query(False),
    search_id: str = Query("", max_length=64),
    via: str = Query("", max_length=16),
):
    return await _ask(request, body.q, limit, include_unclaimed, search_id, via)
