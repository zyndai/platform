"""
Persona API routes — registration, profile, threads, search proxy.

Phase 4 migration: cross-agent traffic moved to A2A v0.3 in agent/a2a_router.py.
This file no longer hosts the legacy webhooks; all the anti-loop heuristics
(turn cap, escalation phrase matcher, halt-note insertion, callback-sender)
went away with them. The TaskFSM in a2a_router naturally produces deterministic
terminal/interrupted states, so the band-aids aren't needed.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any, List

import config
from agent.persona_manager import (
    create_persona,
    delete_persona,
    get_brief,
    get_persona_status,
    init_brief_doc,
    purge_user_account,
    update_persona_profile,
)

router = APIRouter()


# Thread lifecycle values written to dm_threads.lifecycle — read by the
# frontend to render the top-of-panel pill. The values are still meaningful
# even though the legacy auto-flips around turn-cap / escalation phrases
# are gone:
#   pending         — thread created, no successful task yet
#   active          — at least one task has completed (set by v3 router)
#   needs_human     — set when the user manually flags a thread for attention
#                     (currently only via UI; phase 4 doesn't auto-flip here)
#   human_handling  — one or both sides flipped their mode to 'human'
LIFECYCLE_PENDING        = "pending"
LIFECYCLE_ACTIVE         = "active"
LIFECYCLE_NEEDS_HUMAN    = "needs_human"
LIFECYCLE_HUMAN_HANDLING = "human_handling"


def _set_thread_status(sb, thread_id: str, new_lifecycle: str, allowed_from: list[str] | None = None) -> None:
    """Idempotent lifecycle transition. If `allowed_from` is given, only
    advance when the current value is in that list — protects later states
    from being clobbered by earlier transitions firing late."""
    try:
        if allowed_from is not None:
            cur = sb.table("dm_threads").select("lifecycle").eq("id", thread_id).execute()
            if not cur.data:
                return
            if cur.data[0].get("lifecycle") not in allowed_from:
                return
        sb.table("dm_threads").update({"lifecycle": new_lifecycle}).eq("id", thread_id).execute()
    except Exception as e:
        print(f"[thread-lifecycle] couldn't set {thread_id} → {new_lifecycle}: {e}")


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


# ── Persona Lifecycle ───────────────────────────────────────────────

@router.get("/{user_id}/status")
async def persona_status(user_id: str):
    """Check if the user has a deployed persona on the network."""
    return get_persona_status(user_id)


@router.post("/register")
async def register_persona(req: PersonaRegisterRequest):
    """
    Register a user as a discoverable agent persona on the Zynd AI Network.
    Derives an Ed25519 keypair from the developer key and registers on zns01.zynd.ai.
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


# ── Brief Google Doc ────────────────────────────────────────────────
#
# The persona's Brief is a Google Doc the agent maintains as the canonical
# long-form context about its principal. Two endpoints:
#   POST /api/persona/{user_id}/brief/init  — create the doc on first use
#   GET  /api/persona/{user_id}/brief       — read current state + content
# Both run under the agent's existing drive.file scope, so the agent can
# only see this single doc — never the user's wider Drive.

@router.post("/{user_id}/brief/init")
async def init_brief(user_id: str):
    """Create the user's Brief Google Doc, or return the existing one."""
    try:
        return init_brief_doc(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/brief")
async def read_brief(user_id: str):
    """Return the user's Brief metadata + current content fetched live from Google Docs."""
    try:
        return get_brief(user_id)
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

    Phase 4.2: routes via A2A v0.3 (signed JSON-RPC message/send) instead
    of the legacy unsigned webhook. The receiver sees a normal v3 message
    on their /a2a/v1 endpoint and processes it like any other inbound
    cross-agent traffic.
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

    # Figure out who the partner is on this thread.
    if t["initiator_id"] in (user_id, my_agent_id):
        partner_agent_id = t["receiver_id"]
    elif t["receiver_id"] in (user_id, my_agent_id):
        partner_agent_id = t["initiator_id"]
    else:
        raise HTTPException(status_code=403, detail="You are not a participant of this thread.")

    # 1. Insert the message into db (sender-side log; receiver sees it
    #    via A2A inbound which mirrors to dm_messages on their side).
    row = sb.table("dm_messages").insert({
        "thread_id": req.thread_id,
        "sender_id": my_agent_id,
        "sender_type": "human",  # the human is typing, not the orchestrator
        "channel": "agent",      # on the agent channel
        "content": req.content,
    }).execute()

    # 2. Look up the partner's stored URL → resolve to the v3 endpoint.
    partner = sb.table("persona_agents").select("webhook_url").eq("agent_id", partner_agent_id).execute()
    partner_url = partner.data[0].get("webhook_url") if partner.data else None
    from agent.a2a.client import A2AClient, A2AError, resolve_a2a_url
    a2a_url = resolve_a2a_url(partner_url) if partner_url else None
    if not a2a_url:
        print(f"[agent-send] ⚠ No A2A endpoint resolvable for {partner_agent_id} — message saved locally only")
        return {
            "status": "saved_only",
            "thread_id": req.thread_id,
            "message": row.data[0] if row.data else None,
            "warning": "Partner has no resolvable A2A endpoint; the message is in the DB but not delivered.",
        }

    # 3. Build the sender's keypair and ship a signed message.
    from agent.persona_manager import _derive_agent_keypair, _load_developer_seed
    from agent.zynd_identity import keypair_from_seed, build_derivation_proof
    persona_row = sb.table("persona_agents").select("derivation_index,public_key").eq("user_id", user_id).execute()
    if not persona_row.data:
        raise HTTPException(status_code=500, detail="Sender persona row missing.")
    index = persona_row.data[0]["derivation_index"]
    dev_seed = _load_developer_seed()
    private_seed, public_key_bytes = _derive_agent_keypair(dev_seed, index)
    keypair = keypair_from_seed(private_seed)
    developer_proof = build_derivation_proof(dev_seed, public_key_bytes, index)

    client = A2AClient(keypair=keypair, entity_id=my_agent_id, developer_proof=developer_proof)
    # Card URL is sibling to the a2a URL (same base + `/.well-known/agent-card.json`).
    # The dispatcher fetches it (cached 5min), reads capabilities + the
    # x-zynd.requiresPushNotification hint, and picks the transport.
    card_url = a2a_url.replace("/a2a/v1", "/.well-known/agent-card.json")
    from agent.a2a.transport import dispatch, Intent
    delivery_result: dict = {"delivered": False}
    try:
        result = await dispatch(
            client,
            peer_entity_id=partner_agent_id,
            peer_a2a_url=a2a_url,
            peer_card_url=card_url,
            user_id=user_id,
            thread_id=req.thread_id,
            context_id=req.thread_id,
            text=req.content,
            intent=Intent.AGENT_TO_AGENT,
            origin_kind="agent_send",
            origin_ref={"thread_id": req.thread_id},
        )
        task = result.task or {}
        delivery_result = {
            "delivered": True,
            "transport": result.transport.value,
            "task_id": task.get("id"),
            "task_state": (task.get("status") or {}).get("state"),
            "callback_id": result.callback_id,
        }
        print(
            f"[agent-send] → {a2a_url} via={result.transport.value} "
            f"task={task.get('id', '')[:8]} state={delivery_result['task_state']}"
        )
    except A2AError as e:
        print(f"[agent-send] ⚠ receiver rejected: {e.code} {e.message} (reason={e.reason})")
        delivery_result = {"delivered": False, "error_code": e.code, "error_reason": e.reason}
    except Exception as e:
        print(f"[agent-send] ⚠ transport error: {type(e).__name__}: {e}")
        delivery_result = {"delivered": False, "error": f"{type(e).__name__}: {e}"}

    return {
        "status": "sent",
        "thread_id": req.thread_id,
        "message": row.data[0] if row.data else None,
        "delivery": delivery_result,
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

    # The schema replaced the single `mode` column with per-side
    # `initiator_mode` / `receiver_mode` (see patch_dm_thread_modes_per_side.sql).
    # The caller's `req.mode` describes how *they* want their side to
    # behave; the receiver's side defaults to 'agent' (their orchestrator
    # picks up first) and they can flip to 'human' from their UI.
    inserted = sb.table("dm_threads").insert({
        "initiator_id": my_agent_id,
        "receiver_id": req.target_agent_id,
        "initiator_name": my_name,
        "receiver_name": req.target_name or "Network Agent",
        "status": "pending",
        "initiator_mode": req.mode,
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


class ThreadStatusUpdate(BaseModel):
    # 'decline' on a pending request, 'revoke' on an accepted connection,
    # or 'unblock' to lift a block. (Accept and block keep using the
    # existing direct-Supabase update path the UI already wires up via
    # the dm_threads RLS policy — no behavior change there.)
    action: str  # 'decline' | 'revoke' | 'unblock'
    user_id: str  # whoever is acting — must be a participant


@router.patch("/threads/{thread_id}/status")
async def update_thread_status(thread_id: str, req: ThreadStatusUpdate):
    """Apply a ConnectionFSM transition driven by the v3 spec §3.1.3.

    Supports the transitions the existing UI doesn't already cover via
    direct Supabase updates:
      • decline: requested → declined  (receiver soft-rejects)
      • revoke:  accepted  → revoked   (either side ends the relationship)
      • unblock: blocked   → accepted  (we don't track prior state yet,
                                         so unblock always lands at accepted
                                         — refine in a later phase)

    Any in-flight a2a_tasks on this thread are transitioned to 'canceled'
    with reason='connection_<action>' so handlers don't keep running on
    a connection that no longer exists (T-2 + EV_T_PERMISSION_REVOKED).
    """
    if req.action not in ("decline", "revoke", "unblock"):
        raise HTTPException(status_code=400, detail="action must be 'decline', 'revoke', or 'unblock'")

    sb = _supabase()
    thread_row = sb.table("dm_threads").select("*").eq("id", thread_id).execute()
    if not thread_row.data:
        raise HTTPException(status_code=404, detail="Thread not found")
    thread = thread_row.data[0]

    side = _my_side(thread, req.user_id)
    if not side:
        raise HTTPException(status_code=403, detail="You are not a participant of this thread.")

    cur_status = thread.get("status") or "pending"

    # Validate the FSM transition.
    transitions = {
        "decline": {"from": ("pending",),  "to": "declined"},
        "revoke":  {"from": ("accepted",), "to": "revoked"},
        "unblock": {"from": ("blocked",),  "to": "accepted"},
    }
    rule = transitions[req.action]
    if cur_status not in rule["from"]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {req.action} a connection in '{cur_status}' state.",
        )
    new_status = rule["to"]

    sb.table("dm_threads").update({"status": new_status}).eq("id", thread_id).execute()

    # Cancel in-flight tasks on this thread per design §3.2.3
    # (EV_T_PERMISSION_REVOKED).
    try:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        sb.table("a2a_tasks").update({
            "state": "canceled",
            "terminal_at": now_iso,
            "failure_reason": f"connection_{req.action}",
            "updated_at": now_iso,
        }).eq("context_id", thread_id).in_(
            "state", ["submitted", "working", "input-required", "auth-required"]
        ).execute()
    except Exception as e:
        print(f"[thread-status] cleanup of in-flight tasks failed: {e}")

    return {"status": "ok", "thread_id": thread_id, "new_status": new_status, "side": side}


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

    # When either side flips to human, the thread is no longer purely an
    # agent-to-agent automation. Flag the status so the UI can render the
    # right pill for both participants.
    if req.mode == "human":
        _set_thread_status(sb, thread_id, LIFECYCLE_HUMAN_HANDLING)

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


