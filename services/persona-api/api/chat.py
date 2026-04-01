"""
Chat route — the main user ↔ agent conversation endpoint.

POST /api/chat/message
  Body: { "message": "Post a tweet saying hello world" }
  Auth: Bearer <supabase_jwt>

Returns the agent's response and any actions it took.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from agent.orchestrator import handle_user_message

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
    """Process a user message through the AI agent."""
    print("user", user)
    print("This user has asked the following message: ", body.message)
    result = await handle_user_message(
        user_id=user["id"],
        message=body.message,
        conversation_id=body.conversation_id,
    )
    return result
