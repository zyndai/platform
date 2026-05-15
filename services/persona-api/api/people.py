"""
People API routes.

This router is the dashboard-facing surface for network discovery. It keeps
the older `/api/persona/*` routes available for persona lifecycle and A2A
transport, while giving the People page names that match the product surface.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.persona_manager import get_persona_status
from api.auth import get_current_user
from api.persona import (
    AgentChannelSend,
    ThreadCreateRequest,
    agent_channel_send,
    create_thread,
)

router = APIRouter()


class IntroductionCreateRequest(BaseModel):
    target_agent_id: str = Field(..., min_length=1)
    target_name: Optional[str] = "Network Agent"
    message: str = Field(..., min_length=1, max_length=4000)


@router.get("/me")
async def my_people_profile(user: dict = Depends(get_current_user)):
    """Return the current user's persona identity for People-page UI state."""
    persona = get_persona_status(user["id"])
    return {
        "user_id": user["id"],
        "deployed": bool(persona.get("deployed")),
        "agent_id": persona.get("agent_id"),
        "name": persona.get("name"),
        "public_path": f"/p/{user['id']}" if persona.get("deployed") else None,
    }


@router.get("/discover")
async def discover_people(
    query: str = Query("persona", min_length=0, max_length=120),
    limit: int = Query(24, ge=1, le=40),
    user: dict = Depends(get_current_user),
):
    """
    Search discoverable personas for the People page.

    Auth is required so the dashboard is not an unauthenticated registry
    scraper, but the response intentionally remains the same compact shape as
    the legacy persona search endpoint.
    """
    _ = user
    from mcp.tools.zynd_network import discover_personas

    return await asyncio.to_thread(discover_personas, query, limit)


@router.post("/introductions")
async def create_people_introduction(
    req: IntroductionCreateRequest,
    user: dict = Depends(get_current_user),
):
    """
    Create/reuse a thread and send the first intro in one People-domain call.

    Internally this still uses the persona thread and signed A2A delivery
    machinery, but callers no longer need to know that implementation detail.
    """
    user_id = user["id"]
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=400, detail="You need to deploy a persona first.")
    if req.target_agent_id == persona.get("agent_id"):
        raise HTTPException(status_code=400, detail="You cannot introduce yourself to your own persona.")

    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    thread_result = await create_thread(
        user_id,
        ThreadCreateRequest(
            target_agent_id=req.target_agent_id,
            target_name=req.target_name or "Network Agent",
            mode="agent",
        ),
    )
    thread = thread_result.get("thread") or {}
    thread_id = thread.get("id")
    if not thread_id:
        raise HTTPException(status_code=500, detail="Could not open the introduction thread.")

    send_result = await agent_channel_send(
        user_id,
        AgentChannelSend(thread_id=thread_id, content=message),
    )

    return {
        "status": "sent",
        "thread_id": thread_id,
        "thread": thread,
        "thread_status": thread_result.get("status"),
        "delivery": send_result.get("delivery"),
        "message": send_result.get("message"),
        "warning": send_result.get("warning"),
    }
