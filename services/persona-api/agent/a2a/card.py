"""
Signed A2A v0.3 agent card builder for agent-persona.

Produces the JSON document served at
  GET /api/persona/{user_id}/.well-known/agent-card.json

The card is signed with the persona's Ed25519 keypair using a
JWS-detached signature over JCS-canonical bytes (RFC 7515 + RFC 8785).
This is the format any A2A v0.3-compliant peer expects.

Why a custom builder rather than using the SDK's BuildCardOptions
plumbing: agent-persona is multi-tenant — every persona shares one
FastAPI process — and the SDK's defaults assume a per-agent base URL.
We have a per-persona path scheme (/api/persona/{user_id}/...) that
needs explicit `url` and `a2a_path` plumbing, and we don't yet need
the Pydantic payload/output_model schema advertisement machinery.
"""

import base64
import json
from datetime import datetime, timezone
from typing import Any, Optional

import config
from agent.a2a.canonical import canonical_bytes
from agent.a2a.types import ZYND_AUTH_VERSION
from agent.persona_manager import (
    _derive_agent_keypair,
    _load_developer_seed,
    _get_supabase,
)
from agent.zynd_identity import (
    Keypair,
    keypair_from_seed,
    generate_developer_id,
    build_derivation_proof,
    sign as ed_sign,
)


_PROTOCOL_VERSION = "0.3.0"


def _persona_base_url(user_id: str) -> str:
    """Public base URL where this persona's A2A endpoints live."""
    base = config.ZYND_WEBHOOK_BASE_URL.rstrip("/")
    # The card and JSON-RPC dispatcher are mounted under /api/persona,
    # so the base URL we advertise on the card is the persona prefix.
    # `url` (the A2A endpoint) is base + a2a_path = /api/persona/{user_id}/a2a/v1.
    return f"{base}/api/persona/{user_id}"


def _now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def build_persona_card_v3(user_id: str) -> Optional[dict[str, Any]]:
    """Build and sign the A2A v0.3 agent card for a deployed persona.

    Returns the signed card dict, or None if the user has no active
    persona. The card is regenerated on every call — Ed25519 sign is
    microseconds and `lastUpdatedAt` needs to be fresh anyway.
    """
    sb = _get_supabase()
    result = (
        sb.table("persona_agents")
        .select("*")
        .eq("user_id", user_id)
        .eq("active", True)
        .execute()
    )
    if not result.data:
        return None

    persona = result.data[0]
    index = persona["derivation_index"]
    agent_id = persona["agent_id"]

    developer_seed = _load_developer_seed()
    private_seed, public_key_bytes = _derive_agent_keypair(developer_seed, index)
    keypair = keypair_from_seed(private_seed)

    # Developer identity + derivation proof. Embedded in the x-zynd block
    # so peers can confirm this card is HD-derived from a known developer
    # without re-querying the registry.
    dev_kp = keypair_from_seed(developer_seed)
    developer_id = generate_developer_id(dev_kp.public_key_bytes)
    developer_proof = build_derivation_proof(developer_seed, public_key_bytes, index)

    base = _persona_base_url(user_id)
    a2a_url = f"{base}/a2a/v1"

    capabilities = {
        "streaming": True,        # we serve message/stream (phase 3)
        "pushNotifications": True, # we serve tasks/pushNotificationConfig/* (phase 3)
        "stateTransitionHistory": False,
    }

    profile = persona.get("profile") or {}

    # Capabilities the persona advertises (informational; permission
    # enforcement is per-connection on dm_threads.permissions, not here).
    persona_caps = persona.get("capabilities") or []
    skill_tags = list(persona_caps) if isinstance(persona_caps, list) else []

    skill: dict[str, Any] = {
        "id": "default",
        "name": persona.get("name") or "Persona",
        "description": persona.get("description") or "",
        "inputModes": ["text/plain", "application/json"],
        "outputModes": ["text/plain", "application/json"],
    }
    if skill_tags:
        skill["tags"] = skill_tags

    security_schemes = {
        "zyndSig": {
            "type": "http",
            "scheme": "ed25519-envelope",
            "description": (
                "Per-message Ed25519 signature in Message.metadata['x-zynd-auth']. "
                "See agent-persona/architecture.md A2A v3 spec."
            ),
        }
    }

    x_zynd: dict[str, Any] = {
        "version": ZYND_AUTH_VERSION,
        "entityId": agent_id,
        "publicKey": keypair.public_key_string,
        "status": "online",
        "lastUpdatedAt": _now_iso(),
        "developerId": developer_id,
        "developerProof": developer_proof,
        "registry": config.ZYND_REGISTRY_URL,
        "category": "persona",
        "tags": ["persona"],
    }
    if profile.get("title"):
        x_zynd["title"] = profile["title"]
    if profile.get("organization"):
        x_zynd["organization"] = profile["organization"]
    if profile.get("location"):
        x_zynd["location"] = profile["location"]

    unsigned: dict[str, Any] = {
        "protocolVersion": _PROTOCOL_VERSION,
        "name": persona.get("name") or "Persona",
        "description": persona.get("description") or "",
        "version": "1.0",
        "url": a2a_url,
        "preferredTransport": "JSONRPC",
        "capabilities": capabilities,
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [skill],
        "securitySchemes": security_schemes,
        "security": [{"zyndSig": []}],
        "x-zynd": x_zynd,
    }

    return _sign_card(unsigned, keypair)


def _sign_card(card: dict[str, Any], keypair: Keypair) -> dict[str, Any]:
    """Attach a JWS-detached signature to an unsigned card.

    Signature input is `<protected_b64>.<JCS_payload_bytes>`. Matches
    the SDK's sign_agent_card byte-for-byte so peers using either SDK
    can verify our cards.
    """
    stripped = {k: v for k, v in card.items() if k not in ("signatures", "signature")}

    protected_header = {"alg": "EdDSA", "typ": "agent-card+jcs+jws"}
    protected_b64 = _b64url_json(protected_header)
    payload_bytes = canonical_bytes(stripped)

    sig_input = protected_b64.encode("ascii") + b"." + payload_bytes
    signature = ed_sign(keypair.private_key, sig_input)
    raw_sig = signature[len("ed25519:"):] if signature.startswith("ed25519:") else signature
    sig_b64url = _b64_to_b64url(raw_sig)

    return {
        **card,
        "signatures": [
            {
                "protected": protected_b64,
                "signature": sig_b64url,
                "header": {"kid": keypair.public_key_string},
            }
        ],
    }


def _b64url_json(obj: Any) -> str:
    encoded = base64.b64encode(
        json.dumps(obj, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return _b64_to_b64url(encoded)


def _b64_to_b64url(b64: str) -> str:
    return b64.rstrip("=").replace("+", "-").replace("/", "_")
