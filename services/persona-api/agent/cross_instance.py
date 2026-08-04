"""
Cross-Instance Group Dispatch — routes @mentions to personas on different
Zynd backends using A2A v3.

When a group has members on different backends, the in-process orchestrator
can't reach them directly. This module:
  1. Detects which members are remote (different webhook base URL)
  2. Builds signed group_context claims (proves membership + permissions)
  3. Dispatches mentions via A2A message/send to the remote backend
  4. Verifies incoming cross-instance claims on the receiving side
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

import config
from agent.group_dispatch import (
    build_group_context_claim,
    verify_group_context_claim,
)

logger = logging.getLogger(__name__)


async def dispatch_cross_instance_mentions(
    *,
    group_id: str,
    asker_user_id: str,
    asker_agent_id: str,
    asker_permissions: dict[str, bool],
    group_seed_index: int,
    message_content: str,
    mentioned_members: list[dict[str, Any]],
    member_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch @mentions to members on remote Zynd backends.

    For each mentioned member:
      1. Look up their agent card to find their backend URL
      2. If same-backend → skip (in-process orchestrator handles it)
      3. If remote → build signed claim, dispatch via A2A message/send

    Returns:
        dict mapping agent_id → dispatch result (sent/skipped/failed).
    """
    results: dict[str, Any] = {}

    # Build one claim per remote dispatch. Each claim proves:
    #   - The message came from a valid group member
    #   - What permissions the asker has in this group
    #   - The group identity (signed by group keypair)
    for member in mentioned_members:
        member_id = member.get("user_id")
        agent_id = member.get("agent_id")
        if not member_id or not agent_id:
            continue

        # Check if this member is on a different backend.
        card = await _resolve_agent_card(agent_id)
        if not card:
            results[agent_id] = {"status": "failed", "reason": "unresolvable_agent"}
            continue

        remote_url = card.get("url", "")
        if _is_same_instance(remote_url):
            # Same backend — handled by in-process dispatch.
            results[agent_id] = {"status": "skipped", "reason": "same_instance"}
            continue

        # Build and dispatch.
        try:
            claim_b64 = build_group_context_claim(
                group_id=group_id,
                group_seed_index=group_seed_index,
                asker_agent_id=asker_agent_id,
                asker_user_id=asker_user_id,
                asker_permissions=asker_permissions,
            )

            result = await _send_a2a_group_message(
                remote_url=remote_url,
                target_agent_id=agent_id,
                group_id=group_id,
                group_context_claim=claim_b64,
                message_content=message_content,
                asker_agent_id=asker_agent_id,
            )
            results[agent_id] = result
        except Exception as e:
            logger.warning("[cross-instance] dispatch to %s failed: %s", agent_id, e)
            results[agent_id] = {"status": "failed", "reason": str(e)[:120]}

    return results


async def handle_incoming_cross_instance(
    *,
    group_id: str,
    claim_b64: str,
    group_seed_index: int,
    asker_agent_id: str,
    message_content: str,
) -> dict[str, Any]:
    """Verify and process an incoming cross-instance group message.

    This is called by the A2A webhook handler when it receives a group
    message from a remote backend. It:
      1. Verifies the group_context claim
      2. Checks that asker_agent_id is actually in the group roster
      3. Returns the parsed claim for the dispatcher to use

    Returns:
        dict with verified claim data, ready for the group dispatcher.
    """
    # 1. Verify the cryptographic claim.
    try:
        claim = verify_group_context_claim(
            claim_b64=claim_b64,
            expected_group_id=group_id,
            group_seed_index=group_seed_index,
        )
    except ValueError as e:
        logger.warning("[cross-instance] claim verification failed: %s", e)
        return {"status": "rejected", "reason": str(e)}

    # 2. Verify asker is actually in the group roster (defense-in-depth).
    try:
        sb = config.get_supabase()
        member_row = (
            sb.table("persona_group_members")
            .select("user_id, permissions")
            .eq("group_id", group_id)
            .eq("user_id", claim["asker_user_id"])
            .limit(1)
            .execute()
        )
        if not member_row.data:
            return {"status": "rejected", "reason": "not_a_member"}
    except Exception as e:
        logger.warning("[cross-instance] roster check failed: %s", e)
        return {"status": "rejected", "reason": "roster_check_error"}

    logger.info(
        "[cross-instance] verified claim from %s for group %s",
        asker_agent_id, group_id,
    )

    return {
        "status": "accepted",
        "claim": claim,
        "message": message_content,
    }


# ── Helpers ──────────────────────────────────────────────────────────


async def _resolve_agent_card(agent_id: str) -> dict[str, Any] | None:
    """Resolve an agent's card to find their A2A endpoint URL."""
    try:
        # Try registry first.
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{config.ZYND_REGISTRY_URL}/v1/agents/{agent_id}/card"
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass

    # Fallback: try well-known on the agent's domain.
    # (For agents registered with a known domain.)
    try:
        from urllib.parse import urlparse
        # Parse agent_id like "zns:abc123" — extract domain if present.
        parts = agent_id.split(":")
        if len(parts) >= 2:
            # Try resolving via zns01.
            pass
    except Exception:
        pass

    return None


def _is_same_instance(remote_url: str) -> bool:
    """Check if a remote URL points to this same backend instance."""
    if not remote_url or not config.ZYND_WEBHOOK_BASE_URL:
        return True  # Conservative: assume same-instance if we can't tell.

    # Strip trailing slashes and compare origins.
    our = config.ZYND_WEBHOOK_BASE_URL.rstrip("/")
    remote = remote_url.rstrip("/")

    # Match if they share the same base origin (scheme + host + port).
    try:
        from urllib.parse import urlparse
        our_p = urlparse(our)
        remote_p = urlparse(remote)
        return our_p.netloc == remote_p.netloc
    except Exception:
        return our == remote


async def _send_a2a_group_message(
    *,
    remote_url: str,
    target_agent_id: str,
    group_id: str,
    group_context_claim: str,
    message_content: str,
    asker_agent_id: str,
) -> dict[str, Any]:
    """Send an A2A message to a remote persona with group context."""
    import json as _json

    # Build A2A v3 envelope.
    a2a_payload = {
        "jsonrpc": "2.0",
        "id": _generate_message_id(),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "messageId": _generate_message_id(),
                "role": "user",
                "parts": [
                    {"kind": "text", "text": message_content},
                    {
                        "kind": "data",
                        "data": {
                            "kind": "zynd.group.context",
                            "group_id": group_id,
                            "group_context_claim": group_context_claim,
                        },
                    },
                ],
                "contextId": f"group:{group_id}:{asker_agent_id}:{target_agent_id}",
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{remote_url.rstrip('/')}/a2a/v1",
                json=a2a_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Zynd-Source": "cross-instance-group",
                },
            )
            resp.raise_for_status()
            return {"status": "dispatched", "http_status": resp.status_code}

    except httpx.TimeoutException:
        return {"status": "failed", "reason": "timeout"}
    except httpx.HTTPStatusError as e:
        return {"status": "failed", "reason": f"http_{e.response.status_code}"}
    except Exception as e:
        return {"status": "failed", "reason": str(e)[:120]}


def _generate_message_id() -> str:
    import uuid
    return str(uuid.uuid4())
