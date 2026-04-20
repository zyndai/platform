"""
Zynd Network MCP tools — discovery, networking, and messaging on the Zynd AI network.

Tools:
  - search_zynd_personas: Search the registry for persona agents
  - get_persona_profile: Fetch a specific persona's full profile
  - list_my_connections: List the user's existing DM threads/connections
  - request_connection: Initiate a new DM thread with a persona
  - check_connection_status: Check if connected to a specific agent
  - message_zynd_agent: Send a message to another persona
"""

import json
import requests
import uuid

import config
from agent.agent_message import AgentMessage


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


def _webhook_from_card(card: dict | None) -> str:
    """Extract the invoke webhook URL from an AgentCard's endpoints block."""
    if not card:
        return ""
    endpoints = card.get("endpoints") or {}
    return endpoints.get("invoke") or endpoints.get("websocket") or ""


def _find_agent_webhook(agent_id: str) -> str | None:
    """Look up an agent's webhook URL — checks local DB first, then registry card endpoint."""
    # Local DB is the source of truth for our platform's personas
    try:
        sb = _get_supabase()
        local = sb.table("persona_agents").select("webhook_url").eq("agent_id", agent_id).execute()
        if local.data and local.data[0].get("webhook_url"):
            return local.data[0]["webhook_url"]
    except Exception:
        pass

    # Fallback to registry card endpoint (endpoints.invoke is the live webhook URL)
    url = _webhook_from_card(_fetch_agent_card(agent_id))
    return url or None


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
            webhook = _webhook_from_card(a.get("card")) or a.get("service_endpoint") or a.get("entity_url") or ""
            if not webhook:
                webhook = _webhook_from_card(_fetch_agent_card(aid))
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
            "webhook_url": _webhook_from_card(card),
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

def message_zynd_agent(user_id: str, target_webhook_url: str, target_agent_id: str, message: str) -> dict:
    """
    Send a structured message to another user's persona on the Zynd network.
    The target must have a webhook URL. Use search_zynd_personas first to find it.

    Args:
        user_id: The ID of the user sending the message (injected automatically).
        target_webhook_url: The webhook URL of the agent you want to message (obtained from search_zynd_personas).
        target_agent_id: The agent_id of the agent you are messaging (obtained from search_zynd_personas).
        message: The natural language request you are sending to the other agent.
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    sender_agent_id = persona.get("agent_id", f"anonymous:{user_id}")

    msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        sender_id=sender_agent_id,
        receiver_id=target_agent_id,
        content=message,
        message_type="query",
    )

    if not target_webhook_url:
        return {"error": "The target agent does not have a webhook URL. They cannot receive messages."}

    try:
        print(f"[zynd_network] Sending to: {target_webhook_url}")

        # Look up the thread_id AND insert the outbound message as a single
        # authoritative dm_messages row on the sender side. Both participants
        # see it immediately via realtime on the shared DB. The receiver's
        # webhook handler will NOT re-insert (B2) — it just triggers the
        # orchestrator when needed.
        thread_id = None
        print(f"[message_zynd_agent] sender={sender_agent_id} user={user_id} target={target_agent_id}")
        try:
            sb = _get_supabase()
            r1 = sb.table("dm_threads").select("id").in_("initiator_id", [sender_agent_id, user_id]).eq("receiver_id", target_agent_id).execute()
            r2 = sb.table("dm_threads").select("id").eq("initiator_id", target_agent_id).in_("receiver_id", [sender_agent_id, user_id]).execute()
            t_data = r1.data or r2.data
            print(f"[message_zynd_agent] thread lookup: r1={len(r1.data or [])} r2={len(r2.data or [])}")
            if t_data:
                thread_id = t_data[0]["id"]
                ins = sb.table("dm_messages").insert({
                    "thread_id": thread_id,
                    "sender_id": sender_agent_id,
                    "sender_type": "agent",
                    "channel": "agent",
                    "content": message,
                }).execute()
                print(f"[message_zynd_agent] ✓ outbound row inserted on thread={thread_id} rows={len(ins.data or [])}")
            else:
                print(f"[message_zynd_agent] ⚠ NO thread found for (me={sender_agent_id}, partner={target_agent_id}) — outbound NOT logged, poll will be skipped")
        except Exception as e:
            print(f"[message_zynd_agent] ⚠ sender-side log failed: {type(e).__name__}: {e}")

        # Always hit the ASYNC webhook (strip /sync suffix if present).
        # The async endpoint returns instantly with {"status": "received"}
        # and the receiver processes in a background task. Hitting the sync
        # endpoint would block until the full orchestrator finishes.
        async_url = target_webhook_url
        if async_url.endswith("/sync"):
            async_url = async_url[:-5]

        # Mark the send time BEFORE the POST so polling can spot any reply
        # that lands afterwards.
        from datetime import datetime, timezone
        send_time_iso = datetime.now(timezone.utc).isoformat()

        # Try to deliver. If the POST itself fails (slow server, timeout,
        # network blip), we DON'T abort — we still poll the DB because the
        # message may have been delivered even if the response didn't reach
        # us, and any reply will land on the shared thread regardless.
        post_error: str | None = None
        try:
            print(f"[message_zynd_agent] POST → {async_url}")
            resp = requests.post(async_url, json=msg.to_dict(), timeout=20)
            resp.raise_for_status()
            print(f"[message_zynd_agent] POST OK ({resp.status_code})")
        except Exception as e:
            post_error = str(e)
            print(f"[message_zynd_agent] POST failed (continuing to poll): {post_error}")

        # Poll the DB for a new agent-channel message on this thread that
        # ISN'T from us. This is the source of truth — if a reply landed,
        # it's there, regardless of what happened to the HTTP response.
        #
        # Budget: 60 seconds. The receiver's orchestrator might need a few
        # iterations (LLM call + tool call + LLM call), each of which can
        # take 5-15s on Gemini. 30s was too tight; replies that landed at
        # T+32s were being missed even though the row was in the DB.
        import time
        reply_text: str | None = None
        if thread_id:
            sb = _get_supabase()
            deadline = time.time() + 60
            print(f"[message_zynd_agent] polling thread={thread_id} for ~60s…")

            def _check_for_reply() -> str | None:
                try:
                    r = (
                        sb.table("dm_messages")
                        .select("content,sender_id,created_at")
                        .eq("thread_id", thread_id)
                        .eq("channel", "agent")
                        .gt("created_at", send_time_iso)
                        .neq("sender_id", sender_agent_id)
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if r.data:
                        content = r.data[0]["content"] or ""
                        # Strip legacy prefixes that might still be on old rows.
                        for prefix in ("[Automated Reply]\n", "[Inbound]\n", "[Async Reply]\n"):
                            if content.startswith(prefix):
                                content = content[len(prefix):]
                                break
                        return content
                except Exception as e:
                    print(f"[message_zynd_agent] poll error: {e}")
                return None

            while time.time() < deadline:
                time.sleep(2)
                found = _check_for_reply()
                if found:
                    reply_text = found
                    print(f"[message_zynd_agent] reply found ({len(found)} chars)")
                    break

            # One last grace check right before giving up — handles the
            # case where the reply landed during the final sleep.
            if not reply_text:
                found = _check_for_reply()
                if found:
                    reply_text = found
                    print(f"[message_zynd_agent] reply found on grace check ({len(found)} chars)")

        # Before returning, check whether the other side created any meeting
        # proposals on this thread during the exchange. Without surfacing
        # these, our AI might re-create a duplicate proposal because the
        # reply text alone doesn't tell it that a ticket already exists.
        recent_proposals: list[dict] = []
        if thread_id:
            try:
                sb = _get_supabase()
                # "Recent" = created at or after we started this send.
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
                if recent_proposals:
                    print(f"[message_zynd_agent] found {len(recent_proposals)} recent proposal(s) on thread")
            except Exception as e:
                print(f"[message_zynd_agent] proposal lookup failed (non-fatal): {e}")

        # Build a guidance note about the proposals so the LLM knows
        # whether to re-propose or just report back to the user.
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

        if reply_text:
            result = {
                "status": "success",
                "reply_status": "reply_received",
                "reply": reply_text,
                "thread_id": thread_id,
                "partner_agent_id": target_agent_id,
                "recent_proposals": recent_proposals,
                "message": "Reply received from the other agent — quote or paraphrase it for the user as your final answer.",
            }
            if proposal_note:
                result["message"] = proposal_note + " Then, " + result["message"]
            return result

        # No reply was found within the polling window.
        if post_error:
            return {
                "status": "delivery_uncertain",
                "reply_status": "no_reply_yet",
                "thread_id": thread_id,
                "partner_agent_id": target_agent_id,
                "post_error": post_error,
                "recent_proposals": recent_proposals,
                "message": (
                    "I tried to send the message but the delivery confirmation didn't come back, "
                    "and no reply has appeared on the thread yet. The other side may not have "
                    "received it. Tell the user the delivery is uncertain and offer to retry."
                ),
            }

        result = {
            "status": "success",
            "reply_status": "no_reply_yet",
            "thread_id": thread_id,
            "partner_agent_id": target_agent_id,
            "recent_proposals": recent_proposals,
            "message": (
                "Message delivered. No reply arrived within ~60s — the other agent "
                "may still be processing, or the other side may be in manual mode "
                "(a human will reply later). Tell the user the message was delivered "
                "and the reply will appear in the Agent Activity tab when it arrives."
            ),
        }
        if proposal_note:
            result["message"] = proposal_note + " Additionally: " + result["message"]
        return result
    except Exception as e:
        return {"error": str(e)}


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
