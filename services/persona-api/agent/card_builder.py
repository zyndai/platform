"""
Persona Card Builder — assembles signed AgentCards for hosted personas.

The Zynd registry's v2 model expects each agent to host its own signed card at
`.well-known/agent.json`. The card declares the agent's invoke/health/card
endpoints, capabilities, and metadata, and is signed with the agent's Ed25519
key. The registry pulls and caches the card so other agents can discover the
correct webhook URL via `GET /v1/entities/{id}/card`.

Because we're multi-tenant — every persona shares one FastAPI process and is
addressed by `/api/persona/webhooks/{user_id}` — we cannot use the SDK's
`build_endpoints()` helper (which assumes a clean per-agent base URL with
fixed `/webhook`/`/webhook/sync` paths). Instead we build the endpoints dict
ourselves with our actual routing scheme, then reuse the SDK's
`sign_agent_card()` to produce the canonical signed payload.
"""

import base64
import json
import time

import config
from agent.persona_manager import (
    _derive_agent_keypair,
    _load_developer_seed,
    _get_supabase,
)
from agent.zynd_identity import Keypair, keypair_from_seed


def _sign_agent_card(card: dict, keypair: Keypair) -> dict:
    """
    Sign an AgentCard and attach the signature field.

    The registry verifies cards by computing canonical JSON of everything
    EXCEPT the `signature` field (sorted keys, no whitespace) and
    verifying the Ed25519 signature against the card's `public_key`.

    Source of truth is the Zynd registry's Go implementation
    (card/fetch.go) — we just have to produce the same canonical bytes.
    """
    card_copy = {k: v for k, v in card.items() if k != "signature"}
    canonical = json.dumps(card_copy, sort_keys=True, separators=(",", ":")).encode()
    card["signature"] = keypair.sign(canonical)
    return card


def _persona_base_url(user_id: str) -> str:
    """The public base URL where this persona's webhooks live."""
    base = config.ZYND_WEBHOOK_BASE_URL.rstrip("/")
    return f"{base}/api/persona/webhooks/{user_id}"


def _build_endpoints(user_id: str) -> dict:
    """Build the endpoints dict for a persona using our actual routing paths."""
    base = _persona_base_url(user_id)
    return {
        "invoke": f"{base}/sync",                    # synchronous webhook
        "invoke_async": base,                         # fire-and-forget webhook
        "health": f"{base}/health",
        "agent_card": f"{base}/.well-known/agent.json",
    }


def _capabilities_to_card_format(capabilities) -> list[dict]:
    """
    Convert our flat capability list (['calendar_management', ...]) into the
    `[{name, category}]` shape that AgentCard schemas expect.
    """
    if not capabilities:
        return []
    if isinstance(capabilities, list):
        return [{"name": c, "category": "service"} for c in capabilities]
    if isinstance(capabilities, dict):
        out = []
        for cat, items in capabilities.items():
            if isinstance(items, list):
                for item in items:
                    out.append({"name": str(item), "category": str(cat)})
            else:
                out.append({"name": str(items), "category": str(cat)})
        return out
    return []


def build_persona_card(user_id: str) -> dict | None:
    """
    Build and sign the AgentCard for a deployed persona.

    Returns the signed card dict, or None if the user has no active persona.
    The card is regenerated on every call — derivation is microseconds and
    the timestamps need to be fresh anyway.
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

    developer_seed = _load_developer_seed()
    private_seed, _public = _derive_agent_keypair(developer_seed, index)
    keypair = keypair_from_seed(private_seed)

    base_url = _persona_base_url(user_id)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    profile = persona.get("profile") or {}

    metadata = {
        "framework": "zynd-multitenant",
        "owner_contact": profile.get("twitter") or profile.get("website") or "",
    }
    if profile.get("title"):
        metadata["title"] = profile["title"]
    if profile.get("organization"):
        metadata["organization"] = profile["organization"]
    if profile.get("location"):
        metadata["location"] = profile["location"]

    card = {
        "agent_id": persona["agent_id"],
        "name": persona["name"],
        "description": persona.get("description") or "",
        "summary": (persona.get("description") or "")[:200],
        "category": "persona",
        "tags": ["persona"],
        "version": "1.0",
        "public_key": keypair.public_key_string,
        "agent_url": base_url,
        "endpoints": _build_endpoints(user_id),
        "capabilities": _capabilities_to_card_format(persona.get("capabilities")),
        "status": "online",
        "last_heartbeat": now_iso,
        "signed_at": now_iso,
        "metadata": metadata,
    }

    return _sign_agent_card(card, keypair)
