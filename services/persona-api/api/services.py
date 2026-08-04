"""
Zynd services API — thin auth-guarded wrappers over the MCP service-discovery
tools. Powers the chat slash commands (/services, /card, /call) so the
frontend can invoke service discovery without round-tripping through the LLM.

The underlying logic lives in mcp.tools.zynd_services. Endpoints here only
add auth, request validation, and JSON shaping for the browser.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from mcp.tools.zynd_services import (
    call_zynd_service,
    get_zynd_service_card,
    search_zynd_services,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    top_k: int = Field(5, ge=1, le=25)
    category: str = Field("", max_length=64)


class CallRequest(BaseModel):
    text: str = ""
    data: Optional[dict] = None


@router.post("/search")
async def services_search(
    body: SearchRequest,
    _user: dict = Depends(get_current_user),
):
    """
    Search the Zynd Network registry for services. Backs the `/services <query>`
    slash command in chat.
    """
    result = await asyncio.to_thread(
        search_zynd_services, body.query, body.top_k, body.category
    )
    return result


@router.get("/card/{entity_id}")
async def services_card(
    entity_id: str,
    _user: dict = Depends(get_current_user),
):
    """Fetch the full agent-card for a given service entity_id."""
    result = await asyncio.to_thread(get_zynd_service_card, entity_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.post("/call/{entity_id}")
async def services_call(
    entity_id: str,
    body: CallRequest,
    _user: dict = Depends(get_current_user),
):
    """
    Invoke a Zynd service. The caller is responsible for shaping `text` and
    `data` per the service's input_schema (which they get from /card).
    """
    if not (body.text or "").strip() and not body.data:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'text' or 'data' must be provided.",
        )
    result = await asyncio.to_thread(
        call_zynd_service, entity_id, body.text or "", body.data or {}
    )
    return result
