"""
Persona Manager — lifecycle management for user personas on the Zynd Network.

Handles:
  - HD key derivation from the developer keypair
  - Agent registration on dns01.zynd.ai with "persona" tags
  - Webhook URL assignment (all routed through this server)
  - Heartbeat registration/deregistration
  - Persona status queries from Supabase
  - Graceful startup (rehydrate active personas) and shutdown

All persona keypairs are deterministically derived from the developer key,
so they can be reconstructed from just the derivation_index — no need to
persist private keys in the database.
"""

import base64
import hashlib
import json
import logging

from supabase import create_client

import config
from agent.heartbeat_manager import get_heartbeat_manager
from agent.zynd_identity import (
    Keypair,
    keypair_from_seed,
    derive_agent_seed,
    load_developer_seed as _load_dev_seed,
    generate_developer_id,
    build_derivation_proof,
)

logger = logging.getLogger(__name__)


def _register_entity_v2(
    keypair: Keypair,
    name: str,
    entity_url: str,
    category: str,
    summary: str,
    tags: list[str],
    capability_summary: dict | None = None,
    version: str | None = None,
    entity_type: str | None = None,
    entity_name: str | None = None,
    developer_id: str | None = None,
    developer_proof: dict | None = None,
) -> str:
    """
    Register an agent on the v2 Zynd registry (POST /v1/entities).

    Canonical signable payload (sorted keys, no whitespace, ensure_ascii=False):
        {category, entity_url, name, public_key, summary, tags}
        + entity_type (only if set)

    Signing must use ensure_ascii=False so non-ASCII chars in name/summary
    (em-dash, emoji, non-English names) serialize as raw UTF-8 — matching
    Go's json.Marshal default. Python's default ensure_ascii=True escapes
    to \\uXXXX which produces different bytes and yields 401 "invalid agent
    signature".

    The POST body carries the signable fields plus `signature` and optional
    extras (capability_summary, entity_type, version, entity_name,
    developer_id, developer_proof).

    Source of truth: zyndai/zyndai-agent dns_registry.py::register_entity
    and the AgentDNS Go server's handleRegisterEntity.
    """
    import requests as req_lib

    signable = {
        "category": category,
        "entity_url": entity_url or "",
        "name": name,
        "public_key": keypair.public_key_string,
        "summary": summary or "",
        "tags": tags or [],
    }
    if entity_type:
        signable["entity_type"] = entity_type
    canonical = json.dumps(
        signable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    signature = keypair.sign(canonical)

    body = {
        "name": name,
        "entity_url": entity_url or "",
        "category": category,
        "tags": tags or [],
        "summary": summary or "",
        "public_key": keypair.public_key_string,
        "signature": signature,
    }
    if entity_type:
        body["entity_type"] = entity_type
    if capability_summary:
        body["capability_summary"] = capability_summary
    if version:
        body["version"] = version
    if entity_name:
        body["entity_name"] = entity_name
    if developer_id:
        body["developer_id"] = developer_id
    if developer_proof:
        body["developer_proof"] = developer_proof

    resp = req_lib.post(
        f"{config.ZYND_REGISTRY_URL}/v1/entities",
        json=body,
        timeout=15,
    )

    raw_text = resp.text or ""
    logger.info(f"[register] POST /v1/entities → {resp.status_code} body={raw_text[:300]}")

    if resp.status_code == 409:
        # Agent already registered — compute the zns: ID locally (same
        # formula the registry uses) and PUT to update name/description/tags.
        agent_id = "zns:" + hashlib.sha256(keypair.public_key_bytes).digest()[:16].hex()
        logger.info(f"[register] 409 — agent already exists, updating {agent_id}")

        updates = {
            "name": name,
            "entity_url": entity_url,
            "category": category,
            "tags": tags or [],
            "summary": summary or "",
        }
        if capability_summary:
            updates["capability_summary"] = capability_summary

        # Two-step signing (matches the registry's update_entity spec):
        #   1. Sign the updates dict (WITHOUT signature key) → body-level sig
        #   2. Sign the FULL body (WITH signature key) → Bearer auth token
        #
        # CRITICAL: we must send `data=raw_bytes` (pre-serialized), NOT
        # `json=dict`. The Go server verifies the Bearer signature against
        # the exact request body bytes. If Python `requests` re-serializes
        # with its own json.dumps (which may differ in whitespace/ordering
        # from our canonical form), the signature won't match.
        body_sig_bytes = json.dumps(
            updates, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        body_sig = keypair.sign(body_sig_bytes)
        updates["signature"] = body_sig

        full_body_bytes = json.dumps(
            updates, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        auth_sig = keypair.sign(full_body_bytes)

        put_resp = req_lib.put(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}",
            data=full_body_bytes,
            headers={
                "Authorization": f"Bearer {auth_sig}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        logger.info(
            f"[register] PUT /v1/entities/{agent_id} → {put_resp.status_code} "
            f"body={put_resp.text[:300] if put_resp.text else ''}"
        )
        if put_resp.status_code not in (200, 204):
            logger.warning(
                f"[register] PUT update returned {put_resp.status_code}, "
                "proceeding with locally-computed ID anyway"
            )
        return agent_id

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to register agent on registry. "
            f"Status: {resp.status_code}, Response: {raw_text[:500]}"
        )

    # Parse the response JSON. The registry is the source of truth for
    # the canonical agent id — we accept `entity_id` (new schema) or
    # `agent_id` (old schema), refusing to proceed if neither is present.
    if not raw_text.strip():
        raise RuntimeError(
            f"Registry returned {resp.status_code} with an empty body. "
            "Cannot determine the canonical agent_id. This is a registry-side "
            "issue — the server accepted the registration but didn't echo the id."
        )

    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"Registry returned non-JSON ({resp.status_code}): {raw_text[:300]}"
        )

    agent_id = data.get("entity_id") or data.get("agent_id")
    if not agent_id:
        raise RuntimeError(
            "Registry accepted the request but did not return an entity_id "
            "or agent_id in the response. Refusing to store a local fallback. "
            f"Response: {str(data)[:300]}"
        )
    return agent_id


def _load_developer_seed() -> bytes:
    """Load the developer Ed25519 seed (32 bytes) from the keypair file."""
    return _load_dev_seed(config.ZYND_DEVELOPER_KEYPAIR_PATH)


def _derive_agent_keypair(developer_seed: bytes, index: int) -> tuple[bytes, bytes]:
    """
    Back-compat shim: returns (private_seed, public_key_bytes) as the
    rest of persona_manager expects. Internally uses zynd_identity for
    the derivation.
    """
    seed = derive_agent_seed(developer_seed, index)
    kp = keypair_from_seed(seed)
    return kp.private_seed, kp.public_key_bytes


def _get_supabase():
    """Get a Supabase client with service role (bypasses RLS)."""
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _next_derivation_index() -> int:
    """Get the next available derivation index from the database."""
    sb = _get_supabase()
    result = sb.table("persona_agents").select("derivation_index").order(
        "derivation_index", desc=True
    ).limit(1).execute()

    if result.data:
        return result.data[0]["derivation_index"] + 1
    return 0


async def create_persona(
    user_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    price: str = "Free",
    agent_handle: str | None = None,
) -> dict:
    """
    Create and register a new persona on the Zynd Network.

    Steps:
      1. Allocate a derivation index
      2. Derive Ed25519 keypair from developer key
      3. Register agent on dns01.zynd.ai with 'persona' tags
      4. Save to persona_agents table
      5. Start heartbeat

    Returns:
        dict with agent_id, public_key, webhook_url, derivation_index
    """
    sb = _get_supabase()

    # Check if user already has a persona
    existing = sb.table("persona_agents").select("agent_id").eq("user_id", user_id).execute()
    if existing.data:
        raise ValueError("User already has a registered persona. Delete it first to create a new one.")

    # 1. Get next derivation index
    index = _next_derivation_index()

    # 2. Derive the agent's keypair from the developer seed + index.
    # The canonical agent_id is NOT set until the registry returns one
    # below — we used to fall back to a locally-computed legacy id here,
    # which created a local/registry id desync. Now we only trust the
    # registry's response.
    developer_seed = _load_developer_seed()
    private_seed, public_key_bytes = _derive_agent_keypair(developer_seed, index)
    keypair = keypair_from_seed(private_seed)
    private_key_b64 = base64.b64encode(private_seed).decode()

    # 3. Build webhook URL
    webhook_base = config.ZYND_WEBHOOK_BASE_URL.rstrip("/")
    webhook_url = f"{webhook_base}/api/persona/webhooks/{user_id}"

    # 4. Register on the Zynd registry. The registry assigns the
    #    canonical agent_id (currently a "zns:" prefixed string) and
    #    returns it in the response. We NEVER compute a local fallback.
    capabilities_dict = {
        "input_types": capabilities,
        "protocols": ["http"],
        "skills": ["persona"],
    }

    # Build developer identity + derivation proof. The registry requires
    # these to confirm this agent key was HD-derived from a known developer
    # key. The proof message is: agent_pub_bytes || big_endian_uint32(index)
    # signed by the developer key.
    dev_keypair = keypair_from_seed(developer_seed)
    developer_id = generate_developer_id(dev_keypair.public_key_bytes)
    developer_proof = build_derivation_proof(developer_seed, public_key_bytes, index)

    try:
        agent_id = _register_entity_v2(
            keypair=keypair,
            name=name,
            entity_url=webhook_url,
            category="persona",
            summary=description[:200] if description else "",
            tags=["persona"],
            capability_summary=capabilities_dict,
            version="1.0",
            entity_type="agent",
            developer_id=developer_id,
            developer_proof=developer_proof,
        )
        logger.info(f"[persona] Registered {agent_id} on registry")
    except RuntimeError as e:
        # 409 = agent already registered on the registry (e.g. a previous
        # partial failure left an orphan). Without the id in our response
        # we can't continue — fail loud so the caller can clean up.
        raise RuntimeError(f"Failed to register agent on registry: {e}")

    # 5. Save to database
    row = {
        "user_id": user_id,
        "agent_id": agent_id,
        "derivation_index": index,
        "public_key": keypair.public_key_string,
        "name": name,
        "description": description,
        "capabilities": capabilities,
        "webhook_url": webhook_url,
        "active": True,
    }
    if agent_handle:
        row["agent_handle"] = agent_handle
    sb.table("persona_agents").insert(row).execute()

    # 6. Start heartbeat
    hb = get_heartbeat_manager()
    await hb.add_agent(agent_id, private_key_b64)

    logger.info(f"[persona] Created persona for user {user_id}: {agent_id} (index={index})")

    return {
        "status": "success",
        "agent_id": agent_id,
        "public_key": keypair.public_key_string,
        "webhook_url": webhook_url,
        "derivation_index": index,
    }


async def delete_persona(user_id: str) -> dict:
    """
    Deregister and clean up a user's persona.

    Steps:
      1. Stop heartbeat
      2. Deregister from registry
      3. Mark inactive in database
    """
    sb = _get_supabase()
    result = sb.table("persona_agents").select("*").eq("user_id", user_id).execute()

    if not result.data:
        raise ValueError("No persona found for this user.")

    persona = result.data[0]
    agent_id = persona["agent_id"]
    index = persona["derivation_index"]

    # 1. Stop heartbeat
    hb = get_heartbeat_manager()
    await hb.remove_agent(agent_id)

    # 2. Deregister from registry
    try:
        import requests as req_lib
        import time as _time

        developer_seed = _load_developer_seed()
        private_seed, _ = _derive_agent_keypair(developer_seed, index)
        keypair = keypair_from_seed(private_seed)

        timestamp = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        sign_message = f"{agent_id}:{timestamp}"
        signature = keypair.sign(sign_message.encode())

        req_lib.delete(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}",
            headers={
                "X-Agent-Signature": signature,
                "X-Timestamp": timestamp,
            },
            timeout=10,
        )
        logger.info(f"[persona] Deregistered {agent_id} from registry")
    except Exception as e:
        logger.warning(f"[persona] Failed to deregister from registry: {e}")

    # 3. Mark inactive (soft delete — preserves derivation_index history)
    sb.table("persona_agents").update({
        "active": False,
    }).eq("user_id", user_id).execute()

    logger.info(f"[persona] Deleted persona for user {user_id}: {agent_id}")
    return {"status": "deleted", "agent_id": agent_id}


async def purge_user_account(user_id: str) -> dict:
    """
    Full account purge. Removes EVERYTHING associated with a user so they
    can sign up fresh with the same Google/LinkedIn account:

      1. Persona: heartbeat stopped, deregistered from the Zynd registry,
         row deleted (hard delete — goes past the soft-delete that
         delete_persona does).
      2. Conversations: all dm_threads the user participated in (keyed
         by the persona's agent_id), and all dm_messages in those
         threads (cascades).
      3. Meeting tickets: agent_tasks rows — cascaded automatically by
         the FK to auth.users.
      4. OAuth tokens: api_tokens rows — cascaded automatically by the
         FK to auth.users.
      5. Chat memory: chat_messages rows — cascaded automatically.
      6. Supabase auth user: deleted via the admin API. Once this lands,
         the user's account is gone; signing back in with the same
         Google/LinkedIn identity creates a brand new auth.users row
         with a brand new UUID.

    There are NO per-persona files to clean up — v2 HD-derivation keeps
    all state in the database. Only the developer seed lives on disk
    and that's shared across all personas.

    NOTE: this is DESTRUCTIVE and IRREVERSIBLE. The endpoint requires
    double confirmation on the frontend before calling.
    """
    sb = _get_supabase()

    result = {"steps": [], "warnings": []}

    # ── 1. Persona cleanup (heartbeat + registry) ──────────────────
    persona_row = sb.table("persona_agents").select("*").eq("user_id", user_id).execute()
    agent_id = None
    if persona_row.data:
        persona = persona_row.data[0]
        agent_id = persona["agent_id"]
        index = persona["derivation_index"]

        # Stop heartbeat — best effort, the agent might not be registered
        try:
            hb = get_heartbeat_manager()
            await hb.remove_agent(agent_id)
            result["steps"].append(f"heartbeat stopped for {agent_id}")
        except Exception as e:
            result["warnings"].append(f"heartbeat stop failed: {e}")

        # Deregister from the Zynd DNS registry
        try:
            import requests as req_lib
            import time as _time

            developer_seed = _load_developer_seed()
            private_seed, _ = _derive_agent_keypair(developer_seed, index)
            keypair = keypair_from_seed(private_seed)

            timestamp = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            sign_message = f"{agent_id}:{timestamp}"
            signature = keypair.sign(sign_message.encode())

            req_lib.delete(
                f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}",
                headers={
                    "X-Agent-Signature": signature,
                    "X-Timestamp": timestamp,
                },
                timeout=10,
            )
            result["steps"].append(f"deregistered {agent_id} from registry")
        except Exception as e:
            result["warnings"].append(f"registry deregister failed: {e}")

    # ── 2. Conversations (dm_threads + dm_messages) ────────────────
    # Threads use TEXT for participant ids (agent_id format), so they
    # don't cascade from auth.users. Delete them explicitly by agent_id.
    # dm_messages rows cascade from dm_threads.
    if agent_id:
        try:
            sb.table("dm_threads").delete().eq("initiator_id", agent_id).execute()
            sb.table("dm_threads").delete().eq("receiver_id", agent_id).execute()
            result["steps"].append("dm_threads + dm_messages deleted")
        except Exception as e:
            result["warnings"].append(f"dm_threads delete failed: {e}")

    # ── 3. Hard-delete persona_agents row ──────────────────────────
    # (The FK CASCADE from auth.users would also do this, but delete
    # it explicitly now so the next step doesn't need to rely on that.)
    try:
        sb.table("persona_agents").delete().eq("user_id", user_id).execute()
        result["steps"].append("persona_agents row deleted")
    except Exception as e:
        result["warnings"].append(f"persona_agents delete failed: {e}")

    # ── 4. Clear stored OAuth tokens explicitly (defence in depth) ──
    # api_tokens has ON DELETE CASCADE on user_id, so auth.users deletion
    # would catch them, but wipe now so if the final step fails we still
    # don't leak Google/LinkedIn refresh tokens.
    try:
        sb.table("api_tokens").delete().eq("user_id", user_id).execute()
        result["steps"].append("api_tokens rows deleted")
    except Exception as e:
        result["warnings"].append(f"api_tokens delete failed: {e}")

    # ── 5. Chat memory (non-critical) ──────────────────────────────
    try:
        sb.table("chat_messages").delete().eq("user_id", user_id).execute()
        result["steps"].append("chat_messages rows deleted")
    except Exception as e:
        result["warnings"].append(f"chat_messages delete failed: {e}")

    # ── 6. Delete the Supabase auth user ───────────────────────────
    # This uses the admin API (service role key). Once this succeeds,
    # the user is fully gone and can sign up fresh with the same
    # Google / LinkedIn identity — they'll get a new auth.users UUID.
    try:
        sb.auth.admin.delete_user(user_id)
        result["steps"].append("supabase auth.users deleted")
    except Exception as e:
        result["warnings"].append(f"auth.users delete failed: {e}")

    logger.info(
        f"[persona] Purged account for user {user_id}: "
        f"{len(result['steps'])} steps, {len(result['warnings'])} warnings"
    )
    return {"status": "purged", **result}

    logger.info(f"[persona] Deleted persona for user {user_id}: {agent_id}")

    return {"status": "deleted", "agent_id": agent_id}


def get_persona_status(user_id: str) -> dict:
    """Check if a user has a deployed persona. Returns status dict."""
    sb = _get_supabase()
    result = sb.table("persona_agents").select("*").eq("user_id", user_id).eq("active", True).execute()

    if not result.data:
        return {"deployed": False}

    persona = result.data[0]
    return {
        "deployed": True,
        "agent_id": persona["agent_id"],
        "name": persona["name"],
        "agent_handle": persona.get("agent_handle"),
        "description": persona["description"],
        "capabilities": persona["capabilities"],
        "profile": persona.get("profile", {}),
        "webhook_url": persona["webhook_url"],
        "public_key": persona["public_key"],
    }


def update_persona_profile(user_id: str, updates: dict) -> dict:
    """
    Update a persona's editable fields (name, description, capabilities, profile).

    Args:
        user_id: The Supabase user UUID
        updates: Dict with any of: name, description, capabilities, profile

    Returns:
        The updated persona status dict
    """
    sb = _get_supabase()
    existing = sb.table("persona_agents").select("*").eq("user_id", user_id).eq("active", True).execute()
    if not existing.data:
        raise ValueError("No active persona found for this user.")

    allowed_fields = {"name", "agent_handle", "description", "capabilities", "profile"}
    patch = {k: v for k, v in updates.items() if k in allowed_fields}
    # Allow explicit clearing of agent_handle by passing an empty string
    if "agent_handle" in patch and patch["agent_handle"] == "":
        patch["agent_handle"] = None
    if not patch:
        raise ValueError("No valid fields to update.")

    sb.table("persona_agents").update(patch).eq("user_id", user_id).execute()

    logger.info(f"[persona] Updated profile for user {user_id}: {list(patch.keys())}")
    return get_persona_status(user_id)


def get_persona_by_agent_id(agent_id: str) -> dict | None:
    """Look up a persona by its agent_id. Returns the full row or None."""
    sb = _get_supabase()
    result = sb.table("persona_agents").select("*").eq("agent_id", agent_id).eq("active", True).execute()
    return result.data[0] if result.data else None


async def startup():
    """
    Called on server boot. Rehydrates all active personas:
      - Loads them from database
      - Reconstructs keypairs from developer key + derivation index
      - Registers them all with the heartbeat manager

    Since derivation is deterministic, no private keys are stored in the DB.

    Supabase is a hard dependency. If the DB is unreachable, we raise —
    the backend should NOT come up in a half-working state. We'd rather
    fail loud than serve requests with a broken persistence layer.
    """
    sb = _get_supabase()
    result = sb.table("persona_agents").select("*").eq("active", True).execute()

    hb = get_heartbeat_manager()

    # Always start the heartbeat loop — even with zero active personas — so
    # that personas created later in this process's lifetime get heartbeated
    # without requiring a server restart. The loop idles cheaply when
    # _agents is empty (heartbeat_manager._heartbeat_loop sleeps 5s).
    await hb.start()

    if not result.data:
        logger.info("[persona] No active personas to rehydrate; heartbeat loop started idle")
        return

    developer_seed = _load_developer_seed()

    count = 0
    for persona in result.data:
        try:
            index = persona["derivation_index"]
            private_seed, _ = _derive_agent_keypair(developer_seed, index)
            private_key_b64 = base64.b64encode(private_seed).decode()

            await hb.add_agent(persona["agent_id"], private_key_b64)
            count += 1
        except Exception as e:
            logger.error(f"[persona] Failed to rehydrate {persona['agent_id']}: {e}")

    logger.info(f"[persona] Rehydrated {count} active personas, heartbeat started")


async def shutdown():
    """Called on server shutdown. Stops all heartbeats gracefully."""
    hb = get_heartbeat_manager()
    await hb.stop()
    logger.info("[persona] Shutdown complete")
