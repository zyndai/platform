"""
Meetings REST API — thin wrappers around services.meetings.

These endpoints power the MessagesPanel ticket card UI. They let the
frontend create, accept/counter/decline, and list meeting proposals
WITHOUT invoking the LLM. The orchestrator uses the same underlying
service module via mcp/tools/scheduling.py so the rules stay in one
place.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import meetings as meetings_svc

router = APIRouter()


# ── Models ───────────────────────────────────────────────────────────

class ProposalPayload(BaseModel):
    title: str
    start_time: str   # ISO-8601
    end_time: str     # ISO-8601
    location: Optional[str] = ""
    description: Optional[str] = ""


class ProposalCreate(BaseModel):
    thread_id: str
    actor_user_id: str
    payload: ProposalPayload


class ProposalRespond(BaseModel):
    actor_user_id: str
    action: str  # 'accept' | 'counter' | 'decline' | 'cancel'
    edits: Optional[dict] = None


# ── Routes ───────────────────────────────────────────────────────────

@router.post("")
async def create_meeting(req: ProposalCreate):
    """Create a meeting proposal on a thread. Called by the UI when the
    user skips the AI and proposes a time manually."""
    try:
        row = meetings_svc.create_proposal(
            thread_id=req.thread_id,
            actor_user_id=req.actor_user_id,
            payload=req.payload.model_dump(),
        )
    except meetings_svc.MeetingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "task": row}


@router.post("/{task_id}/respond")
async def respond_to_meeting_route(task_id: str, req: ProposalRespond):
    """Accept, counter, decline, or cancel an existing proposal."""
    try:
        row = meetings_svc.respond_to_proposal(
            task_id=task_id,
            actor_user_id=req.actor_user_id,
            action=req.action,
            edits=req.edits,
        )
    except meetings_svc.MeetingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "task": row}


@router.get("/thread/{thread_id}")
async def list_thread_meetings(thread_id: str, include_resolved: bool = False):
    """Return all meeting tickets on a thread. Used by MessagesPanel on open."""
    rows = meetings_svc.list_for_thread(thread_id, include_resolved=include_resolved)
    return {"status": "ok", "tasks": rows}


@router.get("/pending/{user_id}")
async def list_pending_meetings_route(user_id: str):
    """Return tickets awaiting the user's action (and those they're waiting on)."""
    return {"status": "ok", **meetings_svc.list_pending_for_user(user_id)}


@router.get("/{task_id}")
async def get_meeting(task_id: str):
    row = meetings_svc.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task": row}
