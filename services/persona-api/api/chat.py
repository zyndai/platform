"""
Chat route — the main user ↔ agent conversation endpoint.

Two endpoints:
  POST /api/chat/message — non-streaming (legacy, returns full reply)
  POST /api/chat/stream  — streaming (SSE events as tokens arrive)

Both auth with the Supabase Bearer JWT.
"""

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

import config
from api.auth import get_current_user
from agent.orchestrator import handle_user_message, handle_user_message_stream

logger = logging.getLogger(__name__)
router = APIRouter()


def _sb():
    return config.get_supabase()


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    # IANA timezone of the user's browser (e.g. "America/Los_Angeles"). The
    # orchestrator surfaces this to the LLM so calendar/meeting tools land at
    # the wall-clock time the user means, not UTC.
    time_zone: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    actions_taken: list[dict] = []
    action_summary: list[dict] | None = None
    conversation_id: str


@router.post("/message", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Process a user message through the AI agent (non-streaming)."""
    result = await handle_user_message(
        user_id=user["id"],
        message=body.message,
        conversation_id=body.conversation_id,
        time_zone=body.time_zone,
    )
    return result


@router.post("/stream")
async def stream_message(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """
    Streaming variant of /message. Returns Server-Sent Events with the
    orchestrator's event stream (text deltas, thinking tokens if the
    provider exposes them, tool calls, tool results, and a final 'done'
    event carrying the full reply + actions_taken + conversation_id).
    """
    async def event_generator():
        try:
            async for event in handle_user_message_stream(
                user_id=user["id"],
                message=body.message,
                conversation_id=body.conversation_id,
                time_zone=body.time_zone,
            ):
                # SSE frame: "data: <json>\n\n"
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as e:
            # Surface a final error event so the client can render it
            err_payload = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {err_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering for streaming
            "Connection": "keep-alive",
        },
    )


@router.get("/history")
async def chat_history(
    user: dict = Depends(get_current_user),
    limit: int = 200,
    conversation_id: str | None = None,
):
    """Return a chat thread (with their own Aria) so /dashboard/chat can
    hydrate state on mount instead of starting fresh every reload.

    If `conversation_id` is given, it's authoritative — return exactly that
    thread's messages (possibly empty, e.g. a "New chat" the user hasn't
    sent anything in yet) rather than falling back to the most recent one.
    Without it, pick the latest conversation_id from chat_messages, same as
    before. The explicit-id path exists because the frontend persists the
    active conversation_id client-side (localStorage) precisely so "New
    chat" then a refresh doesn't silently resurrect the old thread just
    because it's still the newest row in the table.
    """
    sb = _sb()
    try:
        if conversation_id:
            rows = (
                sb.table("chat_messages")
                .select("*")
                .eq("user_id", user["id"])
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return {
                "conversation_id": conversation_id,
                "messages": rows.data or [],
            }

        latest = (
            sb.table("chat_messages")
            .select("conversation_id,created_at")
            .eq("user_id", user["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not latest.data:
            return {"conversation_id": None, "messages": []}
        conversation_id = latest.data[0]["conversation_id"]

        rows = (
            sb.table("chat_messages")
            .select("*")
            .eq("user_id", user["id"])
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return {
            "conversation_id": conversation_id,
            "messages": rows.data or [],
        }
    except Exception as e:
        logger.warning(f"[chat] history fetch failed for {user['id']}: {e}")
        return {"conversation_id": None, "messages": []}


@router.get("/conversations")
async def list_conversations(
    user: dict = Depends(get_current_user),
    limit: int = 30,
):
    """List the user's past chat sessions for the history sidebar — one
    entry per conversation_id, newest activity first, with a short preview
    so a "New chat" thread that's since been abandoned is still findable.

    No GROUP BY support in the Supabase client, so this pulls a recent
    window of raw messages and groups them in Python. Fine at this scale
    (a few thousand rows covers months of usage) — revisit with a real
    aggregate query if that stops being true.
    """
    sb = _sb()
    try:
        rows = (
            sb.table("chat_messages")
            .select("conversation_id,role,content,created_at")
            .eq("user_id", user["id"])
            .order("created_at", desc=True)
            .limit(2000)
            .execute()
        )
        sessions: dict[str, dict] = {}
        order: list[str] = []
        for row in rows.data or []:
            cid = row["conversation_id"]
            if cid not in sessions:
                sessions[cid] = {
                    "conversation_id": cid,
                    "updated_at": row["created_at"],
                    "preview": None,
                    "message_count": 0,
                }
                order.append(cid)
            sessions[cid]["message_count"] += 1
            # Rows arrive newest-first; the last user message we see for a
            # conversation (i.e. its oldest, since we're walking backward)
            # is the best one-line summary of what the thread was about.
            if row["role"] == "user":
                sessions[cid]["preview"] = row["content"]

        conversations = []
        for cid in order[:limit]:
            s = sessions[cid]
            preview = (s["preview"] or "").strip().replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            conversations.append({
                "conversation_id": cid,
                "preview": preview or "New chat",
                "updated_at": s["updated_at"],
                "message_count": s["message_count"],
            })
        return {"conversations": conversations}
    except Exception as e:
        logger.warning(f"[chat] conversations list failed for {user['id']}: {e}")
        return {"conversations": []}
