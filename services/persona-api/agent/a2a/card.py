"""
Signed A2A v0.3 agent card builder for agent-persona.

Produces the JSON document served at
  GET /api/persona/{user_id}/.well-known/agent-card.json

The card is signed with the persona's Ed25519 keypair using a
JWS-detached signature over JCS-canonical bytes (RFC 7515 + RFC 8785).
This is the format any A2A v0.3-compliant peer expects — both the
TypeScript SDK (`zyndai`) and the Python SDK (`zyndai-agent`).

Why a custom builder rather than calling into the SDK's BuildCardOptions
plumbing: agent-persona is multi-tenant — every persona shares one
FastAPI process — and the SDK's helpers assume a per-agent base URL.
We have a per-persona path scheme (/api/persona/{user_id}/...) that
needs explicit `url` and `a2a_path` plumbing.

Field-level parity with `zyndai_agent.a2a.card.build_agent_card` is
maintained explicitly — anything that ships a `requiresPushNotification`
hint, a `pricing` block, an `inputSchema`/`outputSchema`, or per-tool
skills must round-trip the same shape so SDK-built peers can read our
cards without special-casing.
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

# Catalog of human-readable skill metadata keyed by the capability name
# stored on persona_agents.capabilities. Anything not in the catalog
# still becomes a skill — it just gets a generic description.
_SKILL_CATALOG: dict[str, dict[str, Any]] = {
    "search": {
        "name": "Network search",
        "description": "Find people on the Zynd Network and pull profile context.",
        "examples": ["Find designers in NYC who ship a lot"],
    },
    "calendar": {
        "name": "Calendar",
        "description": "Read calendars and propose meeting times.",
        "examples": ["When am I free for a 30-min on Wednesday?"],
    },
    "twitter": {
        "name": "Twitter / X",
        "description": "Post tweets and send DMs on X.",
        "examples": ["Draft a tweet announcing the new feature"],
    },
    "linkedin": {
        "name": "LinkedIn",
        "description": "Post updates, send DMs, and look up LinkedIn profiles.",
        "examples": ["Send a follow-up note to Alice on LinkedIn"],
    },
    "notion": {
        "name": "Notion",
        "description": "Read, search, and write to Notion databases and pages.",
        "examples": ["Save this idea to my Notion inbox"],
    },
    "gmail": {
        "name": "Gmail",
        "description": "Search, send, and triage Gmail.",
        "examples": ["Draft a reply to the latest message from Acme"],
    },
    "docs": {
        "name": "Google Docs",
        "description": "Create and edit Google Docs and Sheets.",
        "examples": ["Spin up a doc with the meeting notes"],
    },
    "messaging": {
        "name": "Agent messaging",
        "description": "Initiate and respond to A2A conversations with other Zynd agents.",
        "examples": ["Reach out to Bob's agent about a coffee chat"],
    },
}

# Default-free pricing block. We advertise the persona as free-to-message
# until x402 micropayments are wired in. Shape matches the SDK's
# `pricing` field semantics so peers can parse it without branching.
_PRICING_FREE_STUB: dict[str, Any] = {
    "model": "free",
    "currency": "USD",
    "rates": {},
    "paymentMethods": [],
}

# Minimal advertised input/output schema. The SDK's builder derives a
# Zod-equivalent JSON schema from a Pydantic model; we hand-roll a
# permissive text+attachments schema that matches what every persona
# accepts via /a2a/v1 message/send.
_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "mimeType": {"type": "string"},
                    "uri": {"type": "string"},
                },
            },
        },
    },
    "required": [],
}
_DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
    },
}


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

    profile = persona.get("profile") or {}
    persona_caps = persona.get("capabilities") or []
    if not isinstance(persona_caps, list):
        persona_caps = []
    cap_tags = [str(c) for c in persona_caps]

    # Personas always serve streaming + push. The persona-side
    # `requiresPushNotification` hint is a service-side declaration —
    # personas leave it false (a peer is allowed to send sync if they
    # want to). A service that only handles async callback responses
    # would set this to true via its config, forcing peers to register
    # a callback before sending.
    requires_push = bool(profile.get("requires_push_notification", False))

    capabilities = {
        "streaming": True,
        "pushNotifications": True,
        "stateTransitionHistory": False,
    }

    # One skill per capability, with friendly metadata from the catalog.
    # Personas with no declared capabilities still advertise a "default"
    # skill so the card is not skill-empty (the A2A spec requires at
    # least one).
    skills: list[dict[str, Any]] = _build_skills(
        persona_name=persona.get("name") or "Persona",
        persona_description=persona.get("description") or "",
        capabilities=cap_tags,
    )

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
        "tags": ["persona", *cap_tags],
        "pricing": _PRICING_FREE_STUB,
        "inputSchema": _DEFAULT_INPUT_SCHEMA,
        "outputSchema": _DEFAULT_OUTPUT_SCHEMA,
        "acceptsFiles": True,
        # Service-style "callback only" hint. Defaults to false for
        # personas. Peers should switch to push-mode transport when true.
        "requiresPushNotification": requires_push,
    }
    desc = persona.get("description") or ""
    if desc:
        x_zynd["summary"] = desc[:200]
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
        "skills": skills,
        "securitySchemes": security_schemes,
        "security": [{"zyndSig": []}],
        "x-zynd": x_zynd,
    }

    # Top-level optional fields. Provider lets peers attribute the
    # persona to its parent organization; iconUrl supplies an avatar
    # the network UI can render in search results.
    org = profile.get("organization")
    if org:
        unsigned["provider"] = {
            "organization": org,
            "url": config.ZYND_WEBHOOK_BASE_URL,
        }
    avatar = profile.get("avatar_url") or profile.get("picture")
    if avatar:
        unsigned["iconUrl"] = avatar

    return _sign_card(unsigned, keypair)


def _build_skills(
    *,
    persona_name: str,
    persona_description: str,
    capabilities: list[str],
) -> list[dict[str, Any]]:
    """Emit one skill per capability, falling back to a default skill
    when the persona declares no capabilities. Mirrors the SDK pattern
    of advertising one skill per advertised tool category.
    """
    in_modes = ["text/plain", "application/json"]
    out_modes = ["text/plain", "application/json"]

    if not capabilities:
        return [{
            "id": "default",
            "name": persona_name,
            "description": persona_description,
            "inputModes": in_modes,
            "outputModes": out_modes,
            "tags": ["persona"],
        }]

    skills: list[dict[str, Any]] = []
    for cap in capabilities:
        meta = _SKILL_CATALOG.get(cap, {
            "name": cap.replace("_", " ").title(),
            "description": f"Persona capability: {cap}.",
            "examples": [],
        })
        skill: dict[str, Any] = {
            "id": cap,
            "name": meta["name"],
            "description": meta["description"],
            "inputModes": in_modes,
            "outputModes": out_modes,
            "tags": [cap],
        }
        if meta.get("examples"):
            skill["examples"] = meta["examples"]
        skills.append(skill)
    return skills


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
