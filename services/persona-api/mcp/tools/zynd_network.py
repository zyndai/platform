"""
Zynd Network MCP tools — discovery, networking, and messaging on the Zynd AI network.

Tools:
  - search_zynd_personas: Search the registry for persona agents
  - get_persona_profile: Fetch a specific persona's full profile
  - list_my_connections: List the user's existing DM threads/connections
  - request_connection: Initiate a new DM thread with a persona
  - check_connection_status: Check if connected to a specific agent
  - message_zynd_agent: Send a message to another persona (A2A v3 — JSON-RPC over the
                       receiver's /a2a/v1 endpoint, signed with x-zynd-auth)
"""

import asyncio
import json
import logging
import requests

import config

logger = logging.getLogger(__name__)


def _fetch_agent_card(agent_id: str) -> dict | None:
    """Fetch an agent's full card from the registry. Card contains endpoints, capabilities, metadata."""
    try:
        resp = requests.get(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}/card",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _agent_url_from_card(card: dict | None) -> str:
    """Extract the persona's A2A endpoint URL from a card.

    Handles both the v0.3 shape (top-level `url`, advertised when
    `preferredTransport=JSONRPC`) and the legacy v2 shape
    (`endpoints.invoke`). For v2 URLs we don't transform — callers
    use resolve_a2a_url to derive the v3 form when sending.
    """
    if not card:
        return ""
    if isinstance(card.get("url"), str) and card.get("preferredTransport") == "JSONRPC":
        return card["url"]
    endpoints = card.get("endpoints") or {}
    return endpoints.get("invoke") or endpoints.get("websocket") or ""


def _get_supabase():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


# ── Discovery Tools ──────────────────────────────────────────────────

def search_zynd_personas(query: str, top_k: int = 5) -> dict:
    """
    Search the Zynd AI Network for other people's agent personas.
    Use this as the FIRST tool when the user asks about finding people, companies, or agents.
    Only returns agents tagged as "persona" to filter out non-persona agents.

    Args:
        query: Name, keyword, or topic to search for (e.g., 'Alice', 'ZyndAI', 'machine learning').
        top_k: Max results to return.
    """
    try:
        if query.lower().strip() in ["all", "any", "everyone", "personas", "agents", "network", "list"]:
            query = "persona"

        print(f"[zynd_network] Searching registry with query: '{query}'")

        resp = requests.post(
            f"{config.ZYND_REGISTRY_URL}/v1/search",
            json={
                "query": query,
                "tags": ["persona"],
                "max_results": top_k,
                "enrich": True,  # include the full AgentCard inline so we get endpoints.invoke
                "status": "any",  # don't filter out agents whose heartbeat is mid-cycle
            },
            timeout=10,
        )
        resp.raise_for_status()

        results = resp.json().get("results", [])

        personas = []
        for a in results:
            caps = a.get("capability_summary") or a.get("capabilities") or {}
            if isinstance(caps, str):
                try:
                    caps = json.loads(caps)
                except Exception:
                    caps = {}

            tags = a.get("tags", [])
            is_persona = "persona" in tags
            if not is_persona and isinstance(caps, dict):
                is_persona = "persona" in caps.get("services", []) or "persona" in caps.get("skills", [])

            if not is_persona:
                continue

            # Registry switched from `agent_id` to `entity_id` in the new schema;
            # accept either so this works across versions.
            aid = a.get("entity_id") or a.get("agent_id") or ""
            # Prefer webhook from search result's inline card (enrich=true), then service_endpoint,
            # then fall back to a card lookup, then to local DB.
            webhook = _agent_url_from_card(a.get("card")) or a.get("service_endpoint") or a.get("entity_url") or ""
            if not webhook:
                webhook = _agent_url_from_card(_fetch_agent_card(aid))
            if not webhook:
                try:
                    sb = _get_supabase()
                    local = sb.table("persona_agents").select("webhook_url").eq("agent_id", aid).execute()
                    if local.data:
                        webhook = local.data[0].get("webhook_url", "")
                except Exception:
                    pass

            personas.append({
                "name": a.get("name"),
                "agent_id": aid,
                "description": a.get("summary") or a.get("description", ""),
                "webhook_url": webhook,
            })

        return {"status": "success", "count": len(personas), "results": personas}
    except Exception as e:
        return {"error": str(e)}


def get_persona_profile(agent_id: str) -> dict:
    """
    Fetch the full profile of a specific persona from the Zynd Network.
    Use this after discovering a persona to get more details about them.

    Args:
        agent_id: The agent_id of the persona (e.g., 'zns:abc123...').
    """
    # First check if they're a local persona (on our platform) with rich profile
    sb = _get_supabase()
    local = sb.table("persona_agents").select("*").eq("agent_id", agent_id).eq("active", True).execute()
    if local.data:
        p = local.data[0]
        return {
            "status": "success",
            "source": "local",
            "name": p["name"],
            "agent_id": p["agent_id"],
            "description": p["description"],
            "capabilities": p["capabilities"],
            "profile": p.get("profile", {}),
            "webhook_url": p["webhook_url"],
        }

    # Otherwise fetch the full card from the registry
    try:
        card = _fetch_agent_card(agent_id)
        if not card:
            return {"error": "Agent not found in registry"}

        metadata = card.get("metadata") or {}
        return {
            "status": "success",
            "source": "registry",
            "name": metadata.get("name") or card.get("name"),
            "agent_id": card.get("agent_id", agent_id),
            "description": metadata.get("description") or card.get("summary") or "",
            "capabilities": card.get("capabilities") or [],
            "webhook_url": _agent_url_from_card(card),
            "status_text": card.get("status"),
            "last_heartbeat": card.get("last_heartbeat"),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Connection Tools ─────────────────────────────────────────────────

def list_my_connections(user_id: str) -> dict:
    """
    List the user's existing network connections (DM threads).
    Shows accepted connections, pending requests, and blocked agents.

    Args:
        user_id: The ID of the user (injected automatically).
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id")

    sb = _get_supabase()

    identifiers = [user_id]
    if my_agent_id:
        identifiers.append(my_agent_id)

    # Fetch all threads where user participates
    threads = []
    for ident in identifiers:
        r1 = sb.table("dm_threads").select("*").eq("initiator_id", ident).execute()
        r2 = sb.table("dm_threads").select("*").eq("receiver_id", ident).execute()
        threads.extend(r1.data or [])
        threads.extend(r2.data or [])

    # Deduplicate by thread id
    seen = set()
    unique = []
    for t in threads:
        if t["id"] not in seen:
            seen.add(t["id"])
            partner_id = t["receiver_id"] if t["initiator_id"] in identifiers else t["initiator_id"]
            partner_name = t["receiver_name"] if t["initiator_id"] in identifiers else t["initiator_name"]
            unique.append({
                "thread_id": t["id"],
                "partner_agent_id": partner_id,
                "partner_name": partner_name or "Unknown",
                "status": t["status"],
                "initiated_by_me": t["initiator_id"] in identifiers,
                "created_at": t["created_at"],
            })

    accepted = [c for c in unique if c["status"] == "accepted"]
    pending = [c for c in unique if c["status"] == "pending"]

    return {
        "status": "success",
        "my_agent_id": my_agent_id,
        "connections": accepted,
        "pending_requests": pending,
        "total_accepted": len(accepted),
        "total_pending": len(pending),
    }


def request_connection(user_id: str, target_agent_id: str, target_name: str = "Network Agent") -> dict:
    """
    Initiate a new connection (DM thread) with another persona on the Zynd Network.
    This sends a connection request that the other persona can accept or decline.

    Args:
        user_id: The ID of the user (injected automatically).
        target_agent_id: The agent_id of the persona you want to connect with.
        target_name: The display name of the target persona.
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id")
    my_name = persona.get("name", "Zynd Agent")

    if not my_agent_id:
        return {"error": "You need to deploy a persona first before connecting with others."}

    sb = _get_supabase()

    # Check if thread already exists
    r1 = sb.table("dm_threads").select("*").eq("initiator_id", my_agent_id).eq("receiver_id", target_agent_id).execute()
    r2 = sb.table("dm_threads").select("*").eq("initiator_id", target_agent_id).eq("receiver_id", my_agent_id).execute()
    existing = (r1.data or []) + (r2.data or [])

    if existing:
        t = existing[0]
        return {
            "status": "already_exists",
            "thread_id": t["id"],
            "connection_status": t["status"],
            "message": f"You already have a {t['status']} connection with {target_name}.",
        }

    # Create new thread in 'agent' mode — the AI initiated it, so the AI
    # should keep handling replies until the user explicitly takes over.
    result = sb.table("dm_threads").insert({
        "initiator_id": my_agent_id,
        "receiver_id": target_agent_id,
        "initiator_name": my_name,
        "receiver_name": target_name,
        "status": "pending",
        "mode": "agent",
    }).execute()

    if result.data:
        # Broadcast notification
        sb_anon = __import__("supabase").create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
        try:
            sb_anon.channel("system_pings").send({
                "type": "broadcast",
                "event": "new_thread",
                "payload": {
                    "receiver_id": target_agent_id,
                    "initiator_id": my_agent_id,
                },
            })
        except Exception:
            pass

        return {
            "status": "success",
            "thread_id": result.data[0]["id"],
            "thread_mode": "agent",
            "partner_name": target_name,
            "partner_agent_id": target_agent_id,
            "message": f"Connection request sent to {target_name}. They will need to accept it.",
        }

    return {"error": "Failed to create connection thread."}


def check_connection_status(user_id: str, target_agent_id: str) -> dict:
    """
    Check if the user is connected to a specific persona.

    Args:
        user_id: The ID of the user (injected automatically).
        target_agent_id: The agent_id of the persona to check.
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id")

    if not my_agent_id:
        return {"connected": False, "status": "no_persona", "message": "You haven't deployed a persona yet."}

    sb = _get_supabase()
    r1 = sb.table("dm_threads").select("*").eq("initiator_id", my_agent_id).eq("receiver_id", target_agent_id).execute()
    r2 = sb.table("dm_threads").select("*").eq("initiator_id", target_agent_id).eq("receiver_id", my_agent_id).execute()
    threads = (r1.data or []) + (r2.data or [])

    if not threads:
        return {"connected": False, "status": "no_thread", "message": "No connection exists with this agent."}

    t = threads[0]
    return {
        "connected": t["status"] == "accepted",
        "status": t["status"],
        "thread_id": t["id"],
        "initiated_by_me": t["initiator_id"] == my_agent_id,
    }


# ── Messaging Tool ───────────────────────────────────────────────────


def _send_via_a2a_v3(
    sender_agent_id: str,
    sender_user_id: str,
    target_agent_id: str,
    target_webhook_url: str,
    context_id: str,
    message_text: str,
) -> dict:
    """Run an A2A v3 JSON-RPC message/send call on a worker thread.

    `mcp_server._call` invokes tool functions synchronously, so we host
    the async A2A client inside an asyncio.run() per call. Each call gets
    a fresh event loop scoped to this thread; httpx.AsyncClient is
    constructed and torn down inside .send(). The overhead is microseconds.
    """
    from agent.a2a.client import (
        A2AClient,
        A2AError,
        extract_reply_text,
        resolve_a2a_url,
    )
    from agent.persona_manager import (
        _derive_agent_keypair,
        _load_developer_seed,
    )
    from agent.zynd_identity import keypair_from_seed, generate_developer_id, build_derivation_proof

    sb = _get_supabase()

    # Resolve the v3 URL from whatever's stored on persona_agents.
    # Personas registered before phase 4.1 store the legacy webhook URL;
    # newer ones store the v3 URL directly. The resolver handles both.
    a2a_url = resolve_a2a_url(target_webhook_url)
    if not a2a_url:
        return {
            "error": (
                "Could not resolve an A2A v3 URL from the partner's stored URL. "
                f"webhook_url={target_webhook_url!r}"
            )
        }

    # Reconstruct the sender's keypair via the same HD-derivation path
    # persona_manager.startup uses on rehydration. Microseconds.
    persona_row = (
        sb.table("persona_agents")
        .select("derivation_index")
        .eq("user_id", sender_user_id)
        .eq("active", True)
        .execute()
    )
    if not persona_row.data:
        return {"error": "Sender persona not found or inactive."}
    index = persona_row.data[0]["derivation_index"]

    dev_seed = _load_developer_seed()
    private_seed, public_key_bytes = _derive_agent_keypair(dev_seed, index)
    keypair = keypair_from_seed(private_seed)

    # Carry developer_proof on every send for now — bytes are cheap and
    # the receiver may require it on first contact within a context. We
    # can drop it on continuations once interrupted-state resume lands
    # in phase 3.4.
    developer_proof = build_derivation_proof(dev_seed, public_key_bytes, index)

    client = A2AClient(
        keypair=keypair,
        entity_id=sender_agent_id,
        developer_proof=developer_proof,
    )

    async def _go() -> dict:
        return await client.send(
            a2a_url,
            text=message_text,
            context_id=context_id,
        )

    try:
        task = asyncio.run(_go())
    except A2AError as e:
        # Translate the receiver's named error reason into a structured
        # tool result so the LLM can refuse / retry / escalate cleanly.
        return {
            "status": "delivery_failed",
            "reply_status": "rejected",
            "thread_id": context_id,
            "partner_agent_id": target_agent_id,
            "error_code": e.code,
            "error_reason": e.reason,
            "message": (
                f"The receiver rejected the message ({e.code}): {e.message}. "
                f"Tell the user what blocked it (reason: {e.reason or 'unspecified'}) "
                f"and offer a next step."
            ),
        }
    except Exception as e:
        # Transport failure (DNS, TLS, 5xx, etc.). Same shape as above so
        # the LLM's existing prompt branches still work.
        return {
            "status": "delivery_failed",
            "reply_status": "transport_error",
            "thread_id": context_id,
            "partner_agent_id": target_agent_id,
            "error": f"{type(e).__name__}: {e}",
            "message": (
                "The message couldn't be delivered. Tell the user the network "
                "request failed and offer to retry."
            ),
        }

    state = ((task.get("status") or {}).get("state")) or "unknown"
    reply_text = extract_reply_text(task)
    return {
        "task": task,
        "task_state": state,
        "reply_text": reply_text,
    }


def message_zynd_agent(user_id: str, target_webhook_url: str, target_agent_id: str, message: str) -> dict:
    """
    Send a structured message to another user's persona on the Zynd network
    via the A2A v0.3 JSON-RPC transport.

    Use `search_zynd_personas` first to find the target's webhook URL.
    The webhook URL stored on the registry is the legacy v2 endpoint —
    we transform it into the v3 `/a2a/v1` URL automatically.

    Args:
        user_id: The ID of the user sending the message (injected automatically).
        target_webhook_url: The legacy webhook URL of the agent you want to message
                            (the v3 URL is derived from this).
        target_agent_id: The agent_id of the agent you are messaging.
        message: The natural language request you are sending to the other agent.
    """
    from agent.persona_manager import get_persona_status

    persona = get_persona_status(user_id)
    sender_agent_id = persona.get("agent_id")
    if not sender_agent_id:
        return {"error": "You haven't deployed a persona yet — cannot send messages."}

    if not target_webhook_url:
        return {"error": "The target agent does not have a webhook URL. They cannot receive messages."}

    log_prefix = f"[message_zynd_agent {sender_agent_id[:12]}→{target_agent_id[:12]}]"

    # Look up the dm_thread (contextId is the dm_threads.id per design C-1).
    sb = _get_supabase()
    r1 = (
        sb.table("dm_threads")
        .select("id,status")
        .in_("initiator_id", [sender_agent_id, user_id])
        .eq("receiver_id", target_agent_id)
        .execute()
    )
    r2 = (
        sb.table("dm_threads")
        .select("id,status")
        .eq("initiator_id", target_agent_id)
        .in_("receiver_id", [sender_agent_id, user_id])
        .execute()
    )
    thread = (r1.data or r2.data or [None])[0]
    if not thread:
        return {
            "error": (
                "No connection thread exists with this agent. Call request_connection "
                "first and wait for the receiver to accept it before messaging."
            ),
        }
    thread_id = thread["id"]
    thread_status = thread.get("status") or "pending"
    if thread_status not in ("accepted",):
        return {
            "error": (
                f"Connection is in '{thread_status}' state — only 'accepted' "
                f"connections may exchange messages. Wait for the other side to accept."
            ),
            "thread_id": thread_id,
        }

    # Insert outbound to dm_messages BEFORE the send (M-1: persist before
    # dispatch). Both participants see it immediately via Supabase realtime.
    try:
        sb.table("dm_messages").insert({
            "thread_id": thread_id,
            "sender_id": sender_agent_id,
            "sender_type": "agent",
            "channel": "agent",
            "content": message,
        }).execute()
    except Exception as e:
        logger.warning(f"{log_prefix} sender-side dm_messages insert failed: {e}")

    # Snapshot the time so the proposal lookup below can scope to "during
    # this exchange". (Receiver's orchestrator may have created an
    # agent_tasks meeting row while serving the request.)
    from datetime import datetime, timezone
    send_time_iso = datetime.now(timezone.utc).isoformat()

    # ── The actual A2A v3 call ──────────────────────────────────────
    delivery = _send_via_a2a_v3(
        sender_agent_id=sender_agent_id,
        sender_user_id=user_id,
        target_agent_id=target_agent_id,
        target_webhook_url=target_webhook_url,
        context_id=thread_id,
        message_text=message,
    )
    if "error" in delivery and "task" not in delivery:
        # Pre-flight failure (no v3 URL, missing keypair, etc.) — pass
        # the error to the LLM so it can explain to the user.
        delivery["thread_id"] = thread_id
        delivery["partner_agent_id"] = target_agent_id
        return delivery

    # `_send_via_a2a_v3` may have returned a `delivery_failed` shape
    # (network or receiver-rejection); pass it through verbatim — the
    # LLM's prompts already know how to phrase those.
    if delivery.get("status") == "delivery_failed":
        return delivery

    task = delivery["task"]
    task_state = delivery["task_state"]
    reply_text = delivery["reply_text"]

    # ── Recent agent_tasks (meeting) lookup ─────────────────────────
    # Even with synchronous reply we keep this — the receiver's
    # orchestrator may have staged a propose_meeting via the approval
    # gate, which lands in pending_approvals; if/when the user approves,
    # an agent_tasks row will appear. We surface any rows created during
    # this exchange so the LLM doesn't issue a duplicate proposal.
    recent_proposals: list[dict] = []
    try:
        pr = (
            sb.table("agent_tasks")
            .select("id,status,initiator_user_id,recipient_user_id,payload,created_at")
            .eq("thread_id", thread_id)
            .eq("type", "meeting")
            .gte("created_at", send_time_iso)
            .order("created_at", desc=True)
            .execute()
        )
        for row in (pr.data or []):
            payload = row.get("payload") or {}
            recent_proposals.append({
                "task_id": row["id"],
                "status": row["status"],
                "title": payload.get("title"),
                "start_time": payload.get("start_time"),
                "end_time": payload.get("end_time"),
                "proposed_by_me": row.get("initiator_user_id") == user_id,
            })
    except Exception as e:
        logger.warning(f"{log_prefix} proposal lookup failed (non-fatal): {e}")

    proposal_note = ""
    if recent_proposals:
        peer_created = [p for p in recent_proposals if not p["proposed_by_me"]]
        mine = [p for p in recent_proposals if p["proposed_by_me"]]
        parts = []
        if peer_created:
            parts.append(
                f"IMPORTANT: the other side already created {len(peer_created)} meeting "
                f"proposal(s) on this thread during this exchange. "
                f"DO NOT call propose_meeting — it would be a duplicate. "
                f"Instead tell the user the proposal is waiting for their review in the Meetings tab, "
                f"and offer to accept/counter/decline on their behalf via respond_to_meeting."
            )
        if mine:
            parts.append(f"You already created {len(mine)} proposal(s) on this thread; do not duplicate.")
        proposal_note = " ".join(parts)

    # ── Map task state → reply_status (back-compat with prior shape) ─
    if task_state == "completed":
        reply_status = "reply_received"
        guide = "Reply received from the other agent — quote or paraphrase it for the user as your final answer."
    elif task_state in ("input-required", "auth-required"):
        # Phase 3.4 wires a real loop; phase 3.1 just surfaces the
        # interrupted state so the user sees what's blocking.
        reply_status = "needs_more_info"
        guide = (
            "The other agent paused mid-task and asked for more info. The question is in the reply. "
            "Bring it to the user verbatim and ask what they'd like to do."
        )
    elif task_state == "failed":
        reply_status = "remote_failed"
        guide = "The other agent's handler failed. Tell the user something went wrong on their side and offer to retry."
    elif task_state == "rejected":
        reply_status = "remote_rejected"
        guide = "The other agent refused the request. Tell the user the connection lacks the necessary permission for this action."
    else:
        reply_status = "no_reply_yet"
        guide = (
            "The other agent acknowledged but didn't produce a reply this turn. The reply will "
            "appear in the Agent Activity tab when it arrives — tell the user we're waiting on them."
        )

    result = {
        "status": "success" if task_state == "completed" else "partial",
        "reply_status": reply_status,
        "reply": reply_text,
        "thread_id": thread_id,
        "task_id": task.get("id"),
        "task_state": task_state,
        "partner_agent_id": target_agent_id,
        "recent_proposals": recent_proposals,
        "message": guide,
    }
    if proposal_note:
        result["message"] = proposal_note + " Then, " + result["message"]
    return result


def read_agent_channel(user_id: str, thread_id: str, limit: int = 20) -> dict:
    """
    Read the most recent agent-channel messages on a DM thread.

    Use this when you need to know what's been said between your agent and
    another agent on a specific connection — e.g. to look up the last thing
    the other side said, check context across multiple turns, or verify
    whether a reply has arrived since your last send. Returns messages
    newest-first.

    Only reads the agent channel (cross-agent and AI-initiated automation
    chatter). Does NOT read the human conversation tab — that's private
    between humans and off-limits to the agent.

    Args:
        user_id: The user whose thread to read (injected automatically).
        thread_id: The dm_threads row id. Get it from list_my_connections
                   or from a prior request_connection / message_zynd_agent
                   result.
        limit: Max number of messages to return (default 20, most recent first).

    Returns a dict with:
        - messages: list of {sender_id, sender_type, content, created_at}
        - thread_id, count, my_agent_id
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id") if persona.get("deployed") else None

    if not my_agent_id:
        return {"error": "No active persona for this user."}

    sb = _get_supabase()

    # Verify the user is a participant of this thread (don't leak other
    # people's agent-channel traffic via a guessed thread_id).
    thread_res = sb.table("dm_threads").select("initiator_id,receiver_id").eq("id", thread_id).execute()
    if not thread_res.data:
        return {"error": f"Thread {thread_id} not found."}
    t = thread_res.data[0]
    if my_agent_id not in (t["initiator_id"], t["receiver_id"]):
        return {"error": "You are not a participant of this thread."}

    try:
        # Clamp limit to a sensible range
        limit = max(1, min(int(limit or 20), 100))
        r = (
            sb.table("dm_messages")
            .select("sender_id,sender_type,content,created_at")
            .eq("thread_id", thread_id)
            .eq("channel", "agent")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as e:
        return {"error": f"Failed to read messages: {e}"}

    rows = r.data or []

    # Tag each row so the LLM can easily tell self-sent from received.
    messages = []
    for m in rows:
        messages.append({
            "sender_id": m.get("sender_id"),
            "sender_type": m.get("sender_type"),
            "content": m.get("content"),
            "created_at": m.get("created_at"),
            "from_me": m.get("sender_id") == my_agent_id,
        })

    return {
        "status": "success",
        "thread_id": thread_id,
        "count": len(messages),
        "my_agent_id": my_agent_id,
        "messages": messages,
    }
