"""
Chat route — the main user ↔ agent conversation endpoint.

Two endpoints:
  POST /api/chat/message — non-streaming (legacy, returns full reply)
  POST /api/chat/stream  — streaming (SSE events as tokens arrive)

Both auth with the Supabase Bearer JWT.
"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import get_current_user
from agent.orchestrator import handle_user_message, handle_user_message_stream

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    actions_taken: list[dict] = []
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
