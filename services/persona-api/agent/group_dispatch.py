"""
Group-mention dispatch — fire the mentioned persona's orchestrator when a
member @-mentions someone in a group room, and post the reply back as a
channel='agent' message.

The orchestrator already understands cross-persona messages via its
external mode (is_external=True + sender_agent_id + external_permissions).
We reuse that path with the group permission set translated into the
external-permission shape: same plumbing, just a different audience.

Brief access is the one capability that doesn't have a 1:1 external
equivalent — by default external peers never see the brief. Members
who opted in via `can_see_brief` (toggled per-member on the group) get
the brief content injected as additional context on top of the standard
external prompt.

Phase-2 scope is in-process / same-instance dispatch:
  * No A2A signed `group_context` envelope yet (the schema reserves
    persona_groups.group_seed_index for the keypair derivation, see
    GROUPS.md → "Phase 2 prerequisites").
  * The cross-instance case will wrap this same logic in an A2A v3
    envelope signed against the group's derived keypair; the receiving
    side runs a verify + this same dispatch.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from supabase import create_client

import config

logger = logging.getLogger(__name__)


# ── Mention parsing ─────────────────────────────────────────────────────
# Match `@displayname` where displayname starts with a capital letter and
# may include ONE additional capitalized word (e.g. "Sarah" or
# "Sarah Smith"), but stops at the first lower-case or punctuation token.
# This matches the rule the composer enforces when the user picks from
# the @-suggestion dropdown — names come from persona_agents.name which
# is capitalised, and the inserted token is followed by a space.
#
# Examples:
#   "@Sarah what time?"           → ["Sarah"]
#   "@Sarah Smith are you free?"  → ["Sarah Smith"]
#   "@Sarah, ping"                → ["Sarah"]
#   "@everyone hi"                → []   (lowercase initial → no match)
_MENTION_RE = re.compile(r"@([A-Z][A-Za-z0-9_]{0,30}(?:\s+[A-Z][A-Za-z0-9_]{0,30})?)")


def extract_mentions(content: str) -> list[str]:
    """Return the raw display-name fragments after each `@`, in order, deduped."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _MENTION_RE.findall(content or ""):
        name = raw.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def resolve_mentions_to_members(mentions: list[str], members: list[dict]) -> list[dict]:
    """
    Map raw mention names → group-member rows. The match is case-insensitive
    and prefers full-string match over prefix; ties resolve to the earliest
    joined member (deterministic).

    Returns the resolved member rows in mention order, deduped on user_id.
    A mention that doesn't match anyone is dropped silently — the user sees
    their typed text but no persona is fired.
    """
    by_name: dict[str, list[dict]] = {}
    for m in members:
        name = (m.get("display_name") or "").strip().lower()
        if not name:
            continue
        by_name.setdefault(name, []).append(m)

    seen_uids: set[str] = set()
    resolved: list[dict] = []
    for raw in mentions:
        key = raw.lower()
        if key in by_name:
            cand = by_name[key][0]
        else:
            # Prefix match (e.g. typed "Sarah" hits "Sarah Smith").
            prefix_hits = [
                rows[0] for n, rows in by_name.items() if n.startswith(key)
            ]
            if not prefix_hits:
                continue
            cand = prefix_hits[0]
        uid = cand.get("user_id")
        if uid and uid not in seen_uids:
            seen_uids.add(uid)
            resolved.append(cand)
    return resolved


# ── Permission translation ──────────────────────────────────────────────
def _group_perms_to_external(group_perms: dict | None) -> dict:
    """
    Translate the per-member group permissions into the external_permissions
    shape the orchestrator already understands.

    Group key                → external key
      can_query_calendar     → can_query_availability
      can_speak_for_group    → can_post_on_my_behalf  (sparingly — only
                               when explicitly granted in the group)
      can_see_brief          → can_view_full_profile  (closest analog;
                               profile + brief share the "private info"
                               umbrella)

    Anything not in the map falls under default-allowed (read-only registry
    lookups), which is the safe baseline.
    """
    g = group_perms or {}
    return {
        "can_query_availability": bool(g.get("can_query_calendar")),
        "can_view_full_profile": bool(g.get("can_see_brief")),
        "can_post_on_my_behalf": bool(g.get("can_speak_for_group")),
    }


# ── Dispatch ────────────────────────────────────────────────────────────
_GROUP_CONVERSATION_PREFIX = "group:"


def _conversation_id_for(group_id: str, target_user_id: str) -> str:
    """
    Stable per-(group, target persona) conversation id so each persona's
    in-group thread has its own history. Different askers in the same
    group share this thread for the same target — the persona sees the
    whole group conversation, not a fresh slate each turn.
    """
    return f"{_GROUP_CONVERSATION_PREFIX}{group_id}:{target_user_id}"


def _supabase():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


async def dispatch_group_mention(
    *,
    group_id: str,
    asker_user_id: str,
    asker_display_name: str,
    asker_agent_id: str | None,
    target_member: dict,
    user_message: str,
    asker_permissions: dict,
) -> None:
    """
    Invoke the target member's persona for an @-mention in a group room
    and post the reply as a `channel='agent'` row.

    The asker's permissions in the group decide what tools the target
    persona may call; we translate them to the existing external_permissions
    shape (see `_group_perms_to_external`).

    All errors are logged but never raised — group dispatch is best-effort.
    A persona that fails to answer just goes silent for that turn; the
    human chat surface keeps working.
    """
    target_uid = target_member["user_id"]
    target_agent_id = target_member.get("agent_id")
    target_display = target_member.get("display_name") or "Persona"

    # Construct a tight, group-aware prompt prefix the target persona sees.
    # The orchestrator's external-mode system prompt already explains
    # "you're an AI agent talking to another agent" — we just need to tell
    # this turn's flavor: "you were @-mentioned in a group room by Y; here
    # is what they asked."
    prefixed_message = (
        f"[Group room context — you were @-mentioned by {asker_display_name} "
        f"in a private group. Reply as your principal's persona would, in 1–3 "
        f"sentences. The other group members will see your reply.]\n\n"
        f"{user_message}"
    )

    external_perms = _group_perms_to_external(asker_permissions)
    conv_id = _conversation_id_for(group_id, target_uid)

    try:
        # Lazy import to keep the API request path light when no @ is fired.
        from agent.orchestrator import handle_user_message
        result = await handle_user_message(
            user_id=target_uid,
            message=prefixed_message,
            conversation_id=conv_id,
            is_external=True,
            sender_agent_id=asker_agent_id,
            external_permissions=external_perms,
        )
    except Exception as e:
        logger.exception(f"[group-dispatch] {target_uid} failed to answer in group {group_id}: {e}")
        _post_system_note(
            group_id,
            f"{target_display}'s persona couldn't reply right now.",
        )
        return

    reply = (result or {}).get("reply") or ""
    if not reply.strip():
        logger.info(f"[group-dispatch] {target_uid} produced an empty reply in group {group_id}")
        return

    try:
        sb = _supabase()
        sb.table("persona_group_messages").insert({
            "group_id": group_id,
            "sender_user_id": target_uid,
            "sender_agent_id": target_agent_id,
            "sender_name": target_display,
            "channel": "agent",
            "content": reply.strip(),
            "metadata": {
                "in_reply_to_user_id": asker_user_id,
                "reason": "group_mention",
            },
        }).execute()
        sb.table("persona_groups").update({
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
    except Exception as e:
        logger.exception(f"[group-dispatch] couldn't persist reply for {target_uid}: {e}")


def _post_system_note(group_id: str, note: str) -> None:
    """Best-effort system message. Failure is swallowed."""
    try:
        sb = _supabase()
        sb.table("persona_group_messages").insert({
            "group_id": group_id,
            "channel": "system",
            "sender_name": "Zynd",
            "content": note,
        }).execute()
    except Exception as e:
        logger.warning(f"[group-dispatch] couldn't post system note in {group_id}: {e}")
