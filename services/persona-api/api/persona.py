"""
Persona API routes — registration, status, webhooks, and deletion.

v2 migration:
  - Uses persona_manager for HD-derived Ed25519 identities
  - Queries persona_agents table instead of filesystem configs
  - Uses agent_id (zns:...) instead of DID (did:polygon:...)
  - Registry at dns01.zynd.ai
"""

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Any, List
import time

import asyncio

import config
from agent.agent_message import AgentMessage
from agent.orchestrator import handle_user_message
from agent.persona_manager import (
    create_persona,
    delete_persona,
    get_persona_status,
    purge_user_account,
    update_persona_profile,
)

router = APIRouter()


# ── Connection permissions ───────────────────────────────────────────
#
# The four v1 permission flags. Defaults are conservative — only meeting
# requests are on out of the box; everything else is opt-in. The DB column
# `dm_threads.permissions` mirrors this shape and the orchestrator's
# external mode (Chunk 2) will read it to gate what foreign agents can do.

CONNECTION_PERMISSION_KEYS = (
    "can_request_meetings",
    "can_query_availability",
    "can_view_full_profile",
    "can_post_on_my_behalf",
)

DEFAULT_CONNECTION_PERMISSIONS: dict[str, bool] = {
    "can_request_meetings":   True,
    "can_query_availability": False,
    "can_view_full_profile":  False,
    "can_post_on_my_behalf":  False,
}


# ── Thread lookup helper ─────────────────────────────────────────────
#
# Webhooks need to find the dm_thread for an incoming message so they can:
#   (a) check whether the thread is in 'human' or 'agent' mode, and
#   (b) log the message under the right thread.
# The previous code just searched by sender alone, which could match the
# wrong thread if two users had the same sender. We now scope the search
# to the receiving user's identifiers (their UUID and their persona's
# agent_id) so the match is unambiguous.

def _supabase():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _find_thread_for(sb, user_id: str, partner_id: str) -> dict | None:
    """Return the dm_thread row between this user (or their persona) and a partner agent, or None."""
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id") if persona.get("deployed") else None

    me_candidates = [user_id]
    if my_agent_id:
        me_candidates.append(my_agent_id)

    for me in me_candidates:
        r = sb.table("dm_threads").select("*").eq("initiator_id", me).eq("receiver_id", partner_id).execute()
        if r.data:
            return r.data[0]
        r = sb.table("dm_threads").select("*").eq("initiator_id", partner_id).eq("receiver_id", me).execute()
        if r.data:
            return r.data[0]
    return None


def _my_side(thread: dict, user_id: str) -> str | None:
    """
    Return 'initiator' or 'receiver' to indicate which side of a dm_thread
    belongs to the given user. Returns None if the user isn't a participant.
    """
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        return None
    my_agent_id = persona["agent_id"]
    if thread.get("initiator_id") == my_agent_id:
        return "initiator"
    if thread.get("receiver_id") == my_agent_id:
        return "receiver"
    return None


def _my_mode(thread: dict, user_id: str) -> str:
    """Return the per-side mode for this user on this thread ('agent' default)."""
    side = _my_side(thread, user_id)
    if side == "initiator":
        return thread.get("initiator_mode") or "agent"
    if side == "receiver":
        return thread.get("receiver_mode") or "agent"
    return "agent"


# ── Models ────────────────────────────────���─────────────────────────

class PersonaRegisterRequest(BaseModel):
    user_id: str
    name: str
    description: str
    capabilities: List[str]
    price: Optional[str] = "Free"
    agent_handle: Optional[str] = None  # optional internal nickname for the AI agent


class PersonaProfileUpdate(BaseModel):
    name: Optional[str] = None
    agent_handle: Optional[str] = None  # pass empty string to clear
    description: Optional[str] = None
    capabilities: Optional[List[str]] = None
    profile: Optional[dict] = None  # {title, organization, location, twitter, linkedin, github, website, interests}


class ThreadModeUpdate(BaseModel):
    mode: str  # 'human' or 'agent'
    user_id: str  # whose side to flip — must be a participant of the thread


class ThreadCreateRequest(BaseModel):
    target_agent_id: str
    target_name: Optional[str] = "Network Agent"
    mode: Optional[str] = "human"  # 'human' (default) or 'agent'


class AgentChannelSend(BaseModel):
    thread_id: str
    content: str


class ThreadPermissionsUpdate(BaseModel):
    # Any subset of CONNECTION_PERMISSION_KEYS — only the keys you pass
    # are merged into the existing permissions JSON.
    can_request_meetings: Optional[bool] = None
    can_query_availability: Optional[bool] = None
    can_view_full_profile: Optional[bool] = None
    can_post_on_my_behalf: Optional[bool] = None


class SyncWebhookResponse(BaseModel):
    status: str
    message_id: str
    response: Any
    timestamp: float


# ── Persona Lifecycle ─────────────��─────────────────────────────────

@router.get("/{user_id}/status")
async def persona_status(user_id: str):
    """Check if the user has a deployed persona on the network."""
    return get_persona_status(user_id)


@router.post("/register")
async def register_persona(req: PersonaRegisterRequest):
    """
    Register a user as a discoverable agent persona on the Zynd AI Network.
    Derives an Ed25519 keypair from the developer key and registers on dns01.zynd.ai.
    """
    import traceback as _tb

    webhook_base = config.ZYND_WEBHOOK_BASE_URL
    if not webhook_base:
        raise HTTPException(
            status_code=500,
            detail="ZYND_WEBHOOK_BASE_URL is not configured."
        )

    try:
        result = await create_persona(
            user_id=req.user_id,
            name=req.name,
            description=req.description,
            capabilities=req.capabilities,
            price=req.price or "Free",
            agent_handle=req.agent_handle,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        # Catch-all with full traceback so we can see WHERE the error is
        tb = _tb.format_exc()
        print(f"[register] UNEXPECTED: {type(e).__name__}: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Unexpected [{type(e).__name__}]: {str(e)}")


@router.delete("/{user_id}")
async def delete_user_persona(user_id: str):
    """Delete a user's persona — stops heartbeat, deregisters from network, marks inactive."""
    try:
        result = await delete_persona(user_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}/account")
async def purge_account(user_id: str):
    """
    Nuclear option: wipe the user's entire account. Used by the "Delete
    Account" button in the danger zone. Removes persona (heartbeat +
    registry + DB row), all DM threads + messages, meeting tickets, OAuth
    tokens, chat history, AND the Supabase auth.users row itself.

    After this lands, the client should sign the user out and redirect
    to login. The user can immediately sign back in with the same
    Google/LinkedIn identity to start fresh.
    """
    try:
        result = await purge_user_account(user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Profile Update ───────────────────────────────────────────────────

@router.put("/{user_id}/profile")
async def update_profile(user_id: str, req: PersonaProfileUpdate):
    """Update a persona's profile — name, description, capabilities, social links."""
    try:
        updates = req.model_dump(exclude_none=True)
        result = update_persona_profile(user_id, updates)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Agent-channel human send ─────────────────────────────────────────
#
# When the user "takes over" the agent channel and types manually in the
# Agent Activity tab, their message needs to reach the other side via the
# same cross-agent webhook protocol the AI uses. This endpoint handles
# that: insert → webhook POST → done. The other side's webhook handler
# will process it normally (orchestrate if their mode='agent', or just
# log it if they've also taken over).

@router.post("/{user_id}/agent-send")
async def agent_channel_send(user_id: str, req: AgentChannelSend):
    """
    Send a human-typed message on the agent channel. Used when the user
    has clicked "Take Over" in the Agent Activity tab and is replying
    manually instead of letting their AI handle it.
    """
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=400, detail="No active persona.")
    my_agent_id = persona["agent_id"]

    sb = _supabase()
    thread = sb.table("dm_threads").select("*").eq("id", req.thread_id).execute()
    if not thread.data:
        raise HTTPException(status_code=404, detail="Thread not found.")
    t = thread.data[0]

    # Figure out who the partner is on this thread
    if t["initiator_id"] in (user_id, my_agent_id):
        partner_agent_id = t["receiver_id"]
    elif t["receiver_id"] in (user_id, my_agent_id):
        partner_agent_id = t["initiator_id"]
    else:
        raise HTTPException(status_code=403, detail="You are not a participant of this thread.")

    # 1. Insert the message into db
    row = sb.table("dm_messages").insert({
        "thread_id": req.thread_id,
        "sender_id": my_agent_id,
        "sender_type": "human",   # the human is typing, not the orchestrator
        "channel": "agent",       # but it's on the agent channel
        "content": req.content,
    }).execute()

    # 2. Send via webhook to the partner (same protocol as message_zynd_agent)
    from mcp.tools.zynd_network import _find_agent_webhook
    import requests as req_lib

    target_webhook = _find_agent_webhook(partner_agent_id)
    if target_webhook:
        # Always hit the async webhook (strip /sync) — same reasoning as
        # message_zynd_agent: the sync endpoint blocks until the full
        # orchestrator finishes, which can take >30s and timeout.
        async_url = target_webhook
        if async_url.endswith("/sync"):
            async_url = async_url[:-5]
        try:
            msg = AgentMessage(
                content=req.content,
                sender_id=my_agent_id,
                message_type="query",
            )
            # Offload the blocking POST to a worker thread so the FastAPI
            # event loop stays free while the request is in flight. Without
            # this, the async_webhook handler on the same backend couldn't
            # even be dispatched to serve our own POST.
            await asyncio.to_thread(
                req_lib.post, async_url, json=msg.to_dict(), timeout=15
            )
        except Exception as e:
            print(f"[agent-send] Webhook delivery failed: {e}")
            # Don't fail the whole request — the message is already in DB.
            # The other side just won't get a webhook push (they'll still
            # see it via realtime if they're on the same platform).

    return {
        "status": "sent",
        "thread_id": req.thread_id,
        "message": row.data[0] if row.data else None,
    }


# ── Threads (create + mode toggle) ───────────────────────────────────

@router.post("/{user_id}/threads")
async def create_thread(user_id: str, req: ThreadCreateRequest):
    """
    Create or reuse a DM thread between this user's persona and a target agent.
    Used by the AI chat hand-off flow when the user clicks "Open Conversation"
    on a discovered persona — defaults to 'human' mode so the user can take
    the conversation over directly.
    """
    if req.mode not in ("human", "agent"):
        raise HTTPException(status_code=400, detail="mode must be 'human' or 'agent'")

    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=400, detail="You need to deploy a persona first.")
    my_agent_id = persona["agent_id"]
    my_name = persona.get("name") or "Zynd Agent"

    sb = _supabase()
    existing = _find_thread_for(sb, user_id, req.target_agent_id)
    if existing:
        return {"status": "exists", "thread": existing}

    inserted = sb.table("dm_threads").insert({
        "initiator_id": my_agent_id,
        "receiver_id": req.target_agent_id,
        "initiator_name": my_name,
        "receiver_name": req.target_name or "Network Agent",
        "status": "pending",
        "mode": req.mode,
    }).execute()

    if not inserted.data:
        raise HTTPException(status_code=500, detail="Failed to create thread.")
    return {"status": "created", "thread": inserted.data[0]}


@router.get("/threads/{thread_id}/permissions")
async def get_thread_permissions(thread_id: str):
    """Return the current per-connection permission set for a thread, with defaults filled in."""
    sb = _supabase()
    r = sb.table("dm_threads").select("permissions").eq("id", thread_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Thread not found")
    stored = r.data[0].get("permissions") or {}
    # Merge with defaults so missing keys come back as their default value
    merged = {**DEFAULT_CONNECTION_PERMISSIONS, **stored}
    return {"thread_id": thread_id, "permissions": merged}


@router.patch("/threads/{thread_id}/permissions")
async def update_thread_permissions(thread_id: str, req: ThreadPermissionsUpdate):
    """
    Merge new permission flags into the thread's permission JSONB.
    Only the keys present in the request body are touched — pass partial
    updates and the rest are preserved.
    """
    incoming = {k: v for k, v in req.model_dump().items() if v is not None}
    if not incoming:
        raise HTTPException(status_code=400, detail="No permission keys provided.")

    # Reject unknown keys defensively (the Pydantic model already gates this,
    # but the constant is the source of truth and this catches drift).
    unknown = set(incoming.keys()) - set(CONNECTION_PERMISSION_KEYS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permission keys: {sorted(unknown)}")

    sb = _supabase()
    existing = sb.table("dm_threads").select("permissions").eq("id", thread_id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Thread not found")

    current = existing.data[0].get("permissions") or {}
    merged = {**DEFAULT_CONNECTION_PERMISSIONS, **current, **incoming}

    sb.table("dm_threads").update({"permissions": merged}).eq("id", thread_id).execute()
    return {"status": "ok", "thread_id": thread_id, "permissions": merged}


@router.patch("/threads/{thread_id}/mode")
async def update_thread_mode(thread_id: str, req: ThreadModeUpdate):
    """
    Flip the CALLER's side of a dm_thread between 'human' (taken over) and
    'agent' (AI handling). Each participant independently owns their own
    side's mode — flipping yours doesn't affect the other side.
    """
    if req.mode not in ("human", "agent"):
        raise HTTPException(status_code=400, detail="mode must be 'human' or 'agent'")

    sb = _supabase()
    thread_row = sb.table("dm_threads").select("*").eq("id", thread_id).execute()
    if not thread_row.data:
        raise HTTPException(status_code=404, detail="Thread not found")
    thread = thread_row.data[0]

    side = _my_side(thread, req.user_id)
    if not side:
        raise HTTPException(status_code=403, detail="You are not a participant of this thread.")

    column = "initiator_mode" if side == "initiator" else "receiver_mode"
    sb.table("dm_threads").update({column: req.mode}).eq("id", thread_id).execute()

    return {
        "status": "ok",
        "thread_id": thread_id,
        "side": side,
        "mode": req.mode,
    }


# ── Search Proxy (for frontend) ──────────────────────────────────────

@router.get("/search")
async def search_personas(query: str = "persona", limit: int = 10):
    """Proxy search to the Zynd registry, filtered to personas only."""
    from mcp.tools.zynd_network import search_zynd_personas
    return search_zynd_personas(query, top_k=limit)


# ── Persona-Hosted Agent Card (v2 discovery) ─────────────────────────
#
# The Zynd registry caches each agent's card and serves it via
# GET /v1/entities/{id}/card. To play by v2 rules each persona hosts its own
# signed AgentCard at .well-known/agent.json so the registry has an
# authoritative source for endpoints, capabilities, and metadata.

@router.get("/webhooks/{user_id}/.well-known/agent.json")
async def persona_agent_card(user_id: str):
    """Return the signed AgentCard for this persona — pulled by the registry."""
    from agent.card_builder import build_persona_card
    card = build_persona_card(user_id)
    if not card:
        raise HTTPException(status_code=404, detail="No active persona for this user.")
    return card


@router.get("/webhooks/{user_id}/health")
async def persona_health(user_id: str):
    """Lightweight liveness probe — referenced by the persona's AgentCard."""
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=404, detail="No active persona for this user.")
    return {"status": "ok", "agent_id": persona.get("agent_id")}


# ── Webhook Routers (Where network messages arrive) ──────────────────

@router.post("/webhooks/{user_id}")
async def async_webhook(user_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Fire-and-forget webhook listener.
    Receives messages from other Zynd Agents and processes in background.
    """
    payload = await request.json()
    message = AgentMessage.from_dict(payload)

    background_tasks.add_task(process_async_webhook, user_id, message)

    return {
        "status": "received",
        "message_id": message.message_id,
        "timestamp": time.time()
    }


async def process_async_webhook(user_id: str, message: AgentMessage):
    """
    Background task: process an incoming agent-channel webhook message.

    Clean rules:
      1. The sender already inserted the dm_messages row (B1). We NEVER
         re-insert the inbound message here — that was the duplicate bug.
      2. If my side's mode is 'human' (I've taken over), we log the
         decision and STOP. The user will reply from the Agent Activity
         tab. No notice round-trip, no HTTP callback.
      3. If my side's mode is 'agent' (AI handling), we run the
         orchestrator. When it finishes, we INSERT a reply row on the
         shared thread. Both participants see it via realtime. No HTTP
         callback to the sender — the DB is the single source of truth.
      4. message_type='response' is no longer produced by anything we
         control (B4 removed the callback). We still short-circuit it in
         case the SDK or an external peer sends one.

    Every branch logs its decision so backend logs show exactly what
    happened for each inbound message.
    """
    sender_id = message.sender_id or "unknown"
    log_prefix = f"[webhook {user_id[:8]} ← {sender_id[:12]}]"
    print(f"\n{log_prefix} received type={message.message_type} content={message.content[:80]!r}")

    try:
        sb = _supabase()
        thread = _find_thread_for(sb, user_id, sender_id)
        thread_id = thread["id"] if thread else None
        my_mode = _my_mode(thread, user_id) if thread else "agent"
        thread_permissions = {**DEFAULT_CONNECTION_PERMISSIONS, **((thread or {}).get("permissions") or {})}
        print(f"{log_prefix} thread={thread_id} my_mode={my_mode}")
    except Exception as e:
        print(f"{log_prefix} ⚠ setup failed: {e}")
        return

    # Response-type messages are short-circuited. We no longer emit these
    # ourselves (B4), but handle them defensively in case some legacy
    # peer sends one.
    if message.message_type == "response":
        print(f"{log_prefix} response-type message — halting without processing")
        return

    # B2: DO NOT re-insert the inbound message. The sender already logged
    # it on the shared DB (message_zynd_agent and agent-send both insert
    # before posting). Re-inserting here created the duplicate [Inbound]
    # rows you've been seeing.

    # B3: If we've taken over, stop here. The human owner will respond
    # manually from the Agent Activity tab. No notice callback — the
    # other side sees their own message in the shared thread and can
    # see the [TAKEN OVER] status on our side if they look.
    if my_mode == "human":
        print(f"{log_prefix} my side is TAKEN OVER — skipping orchestrator (no auto-reply)")
        return

    # Run the orchestrator. Any exception gets logged as an agent-channel
    # row so the sender sees what went wrong instead of silent failure.
    print(f"{log_prefix} → orchestrator")
    try:
        # C1: use thread_id as the conversation_id so the orchestrator
        # accumulates history across multi-turn agent-to-agent exchanges
        # on the same thread. Fallback to message_id for threadless first
        # contact (shouldn't happen in v1 same-platform but safe).
        conv_id = f"thread:{thread_id}" if thread_id else f"msg:{message.message_id}"
        result = await handle_user_message(
            user_id=user_id,
            message=message.content,
            conversation_id=conv_id,
            is_external=True,
            sender_agent_id=sender_id,
            external_permissions=thread_permissions,
        )
        reply = result.get("reply") or "(empty reply)"
    except Exception as e:
        reply = f"[orchestrator error] {e}"
        print(f"{log_prefix} ⚠ orchestrator crashed: {e}")

    print(f"{log_prefix} reply ready ({len(reply)} chars): {reply[:80]!r}")

    # Insert the reply as a new dm_messages row. This IS the delivery —
    # both sender and receiver see it via realtime on the shared DB. No
    # HTTP callback needed (B4).
    if thread_id:
        try:
            persona = get_persona_status(user_id)
            my_agent_id = persona.get("agent_id", user_id)
            sb.table("dm_messages").insert({
                "thread_id": thread_id,
                "sender_id": my_agent_id,
                "sender_type": "agent",
                "channel": "agent",
                "content": reply,
            }).execute()
            print(f"{log_prefix} reply logged to thread {thread_id}")
        except Exception as e:
            print(f"{log_prefix} ⚠ failed to insert reply row: {e}")
    else:
        print(f"{log_prefix} no thread_id — reply not persisted (first-contact edge case)")


@router.post("/webhooks/{user_id}/sync", response_model=SyncWebhookResponse)
async def sync_webhook(user_id: str, request: Request):
    """
    Synchronous webhook. Other agents hit this when waiting for an immediate answer.

    Behavior depends on the thread's `mode`:
      - 'agent' (or no thread): run the orchestrator and reply within the request.
      - 'human': log the message and return a polite "queued for the human" response,
                 without invoking the orchestrator.
    """
    payload = await request.json()
    try:
        message = AgentMessage.from_dict(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid AgentMessage format: {str(e)}")

    sender_id = message.sender_id or "unknown"
    log_prefix = f"[sync {user_id[:8]} ← {sender_id[:12]}]"
    print(f"\n{log_prefix} received: {message.content[:80]!r}")

    sb = _supabase()
    thread = _find_thread_for(sb, user_id, sender_id)
    thread_id = thread["id"] if thread else None
    my_mode = _my_mode(thread, user_id) if thread else "agent"
    thread_permissions = {**DEFAULT_CONNECTION_PERMISSIONS, **((thread or {}).get("permissions") or {})}
    print(f"{log_prefix} thread={thread_id} my_mode={my_mode}")

    # B2: We do NOT re-insert the inbound message. The sender already
    # logged it (same-platform shared DB). The receiver just processes.

    # B3: If we've taken over, return an ack WITHOUT running the
    # orchestrator and WITHOUT logging anything. The sender's row is
    # already in the shared DB; our human will reply when ready.
    if my_mode == "human":
        print(f"{log_prefix} my side is TAKEN OVER — returning ack")
        return SyncWebhookResponse(
            status="queued",
            message_id=message.message_id,
            response=(
                "Thanks — the person I represent has taken over this conversation personally. "
                "Your message has been delivered and they will reply when available."
            ),
            timestamp=time.time(),
        )

    # AI Handling mode: orchestrate and reply
    try:
        conv_id = f"thread:{thread_id}" if thread_id else f"msg:{message.message_id}"
        result = await handle_user_message(
            user_id=user_id,
            message=message.content,
            conversation_id=conv_id,
            is_external=True,
            sender_agent_id=sender_id,
            external_permissions=thread_permissions,
        )
        reply = result.get("reply", "I am unable to assist right now.")
        print(f"{log_prefix} reply ready ({len(reply)} chars)")
    except Exception as e:
        reply = f"[orchestrator error] {e}"
        print(f"{log_prefix} ⚠ orchestrator crashed: {e}")

    # Log outbound reply. The sync caller ALSO gets it in the HTTP
    # response body, but logging to the shared thread ensures both
    # participants see it via realtime regardless of what the caller
    # does with the response.
    if thread_id:
        try:
            persona = get_persona_status(user_id)
            my_agent_id = persona.get("agent_id", user_id)
            sb.table("dm_messages").insert({
                "thread_id": thread_id,
                "sender_id": my_agent_id,
                "sender_type": "agent",
                "channel": "agent",
                "content": reply,
            }).execute()
        except Exception as e:
            print(f"{log_prefix} ⚠ failed to insert reply row: {e}")

    return SyncWebhookResponse(
        status="success",
        message_id=message.message_id,
        response=reply,
        timestamp=time.time(),
    )
