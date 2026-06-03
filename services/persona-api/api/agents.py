"""Zynd network discovery API — unified search across personas, services,
and standalone agents. Powers the `/agents <query>` slash command.

Card fetch + call are reused from /api/services/* — the registry returns
the same card shape regardless of entity kind, so there's no point in
duplicating those endpoints here.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import get_current_user
from mcp.tools.zynd_network import search_zynd_network

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field("", max_length=200)
    top_k: int = Field(8, ge=1, le=25)
    kind: str = Field("any", max_length=16)


@router.post("/search")
async def agents_search(
    body: SearchRequest,
    _user: dict = Depends(get_current_user),
):
    """Search the Zynd Network for ANY callable entity (personas + services
    + agents). Powers the `/agents <query>` chat slash command."""
    return await asyncio.to_thread(
        search_zynd_network, body.query, body.top_k, body.kind
    )
