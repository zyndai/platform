"""
Public search API — unauthenticated people search for external callers.

One endpoint, one stable path on every deployment (only the host differs):
  POST /api/public/search/people

Callable by ChatGPT Actions, custom agents, or plain curl. No auth by
design — the response only exposes what the persona network already makes
discoverable (name, description, agent_id, avatar), and a light in-memory
per-IP rate limit keeps the endpoint from being used to hammer the
registry or the database.

Two modes, both reusing the in-app search machinery:
  - mode="domain"  → search_zynd_personas (bio-aware ranked people search)
  - mode="similar" → search_similar_people (rank by capability/interest
                     overlap with the free-text query itself)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from mcp.tools.zynd_network import search_similar_people, search_zynd_personas

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory per-IP rate limit ──────────────────────────────────────
# Public endpoint → keep anonymous callers from turning it into a free
# scraping or load-generation tool. Soft guard, not a hard security
# boundary: the data served is already public on the network.
_WINDOW_SECONDS = 60.0
_MAX_PER_WINDOW = 30
_hits: dict[str, tuple[float, int]] = {}
_lock = threading.Lock()


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _lock:
        entry = _hits.get(ip)
        if entry and now - entry[0] < _WINDOW_SECONDS:
            count = entry[1] + 1
            _hits[ip] = (entry[0], count)
            return count > _MAX_PER_WINDOW
        _hits[ip] = (now, 1)
        # Bound the map — drop stale entries so long-running processes
        # don't accumulate unbounded state.
        if len(_hits) > 1024:
            _hits.clear()
        return False


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class PeopleSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    mode: Literal["domain", "similar"] = "domain"
    limit: int = Field(10, ge=1, le=40)


@router.post("/search/people")
async def search_people(req: PeopleSearchRequest, request: Request):
    """Search personas by domain/role (mode='domain') or by similarity to
    a free-text description (mode='similar'). Public — no auth required."""
    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests — slow down.")

    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query must not be empty")

    if req.mode == "similar":
        result = await asyncio.to_thread(search_similar_people, query, req.limit)
    else:
        result = await asyncio.to_thread(search_zynd_personas, query, req.limit, "")

    result["mode"] = req.mode
    result["limit"] = req.limit
    return result