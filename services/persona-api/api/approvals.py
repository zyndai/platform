"""
Approvals API — exposes the pending_approvals table to the frontend.

The orchestrator stages commitment-class tool calls (propose_meeting, etc.)
as rows in pending_approvals instead of firing them. The user resolves
each row via this endpoint; on approve we run the original tool with the
saved args, on decline we mark it as such and (if a thread is attached)
push a polite refusal back to the foreign agent.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client

import config
from api.auth import get_current_user
from agent.persona_manager import get_persona_status

logger = logging.getLogger(__name__)
router = APIRouter()


def _sb():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


class DecideRequest(BaseModel):
    decision: str  # "approve" or "decline"


@router.get("/")
async def list_approvals(user: dict = Depends(get_current_user)):
    """Return all not-yet-decided approvals for the current user, freshest first."""
    sb = _sb()
    r = (
        sb.table("pending_approvals")
        .select("*")
        .eq("user_id", user["id"])
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )
    rows = r.data or []
    # Filter out expired rows in-line (cheaper than running a maintenance job).
    now = datetime.now(timezone.utc)
    fresh: list[dict] = []
    expired_ids: list[str] = []
    for row in rows:
        try:
            exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        except Exception:
            exp = None
        if exp and exp < now:
            expired_ids.append(row["id"])
        else:
            fresh.append(row)
    if expired_ids:
        sb.table("pending_approvals").update({"status": "expired"}).in_("id", expired_ids).execute()
    return {"approvals": fresh}


@router.post("/{approval_id}/decide")
async def decide(
    approval_id: str,
    body: DecideRequest,
    user: dict = Depends(get_current_user),
):
    """Approve or decline a pending tool call.

    On approve we re-run the tool with the saved args via the MCP server;
    if the underlying tool succeeds we record its result on the row and
    return it. On decline we drop a system-style row into the originating
    thread (when there is one) so the foreign agent's user can see the
    polite no.
    """
    if body.decision not in ("approve", "decline"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'decline'")

    sb = _sb()
    row = (
        sb.table("pending_approvals")
        .select("*")
        .eq("id", approval_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Approval not found")
    approval = row.data[0]
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Already {approval['status']}")

    decided_at = datetime.now(timezone.utc).isoformat()

    if body.decision == "approve":
        try:
            from mcp.server import mcp_server
            tool_name: str = approval["tool_name"]
            tool_args: dict = approval["tool_args"] or {}
            result = await asyncio.to_thread(mcp_server._call, tool_name, tool_args)
            sb.table("pending_approvals").update({
                "status": "approved",
                "decided_at": decided_at,
                "result": result if isinstance(result, (dict, list)) else {"value": str(result)},
            }).eq("id", approval_id).execute()
            return {"status": "approved", "result": result}
        except Exception as e:
            logger.error(f"[approvals] tool {approval.get('tool_name')} crashed on approve: {e}")
            sb.table("pending_approvals").update({
                "status": "approved",
                "decided_at": decided_at,
                "result": {"error": f"Tool execution failed: {e}"},
            }).eq("id", approval_id).execute()
            raise HTTPException(status_code=500, detail=f"Tool failed: {e}")

    # Decline path. Drop a system note on the source thread so the foreign
    # side sees a polite refusal in their UI, then mark the row.
    thread_id = approval.get("thread_id")
    if thread_id:
        try:
            persona = get_persona_status(user["id"])
            my_agent_id = persona.get("agent_id", user["id"])
            sb.table("dm_messages").insert({
                "thread_id": thread_id,
                "sender_id": my_agent_id,
                "sender_type": "system",
                "channel": "agent",
                "content": "My principal isn't able to commit to that right now.",
            }).execute()
        except Exception as e:
            logger.warning(f"[approvals] couldn't post decline note to thread {thread_id}: {e}")

    sb.table("pending_approvals").update({
        "status": "declined",
        "decided_at": decided_at,
    }).eq("id", approval_id).execute()
    return {"status": "declined"}
