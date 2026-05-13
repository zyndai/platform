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

import base64
import json
import logging
import re
import time
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

    Group key                → external key(s)
      can_query_calendar     → can_query_availability
      can_speak_for_group    → can_post_on_my_behalf
      can_see_brief          → can_see_brief AND can_view_full_profile

    `can_see_brief` is the umbrella "private info" toggle in group MVP —
    granting it to a member lets the target persona share both the brief
    Google Doc body AND the profile fields (title, org, location, etc.)
    with that asker. The orchestrator now reads them as two independent
    gates, but the group UI exposes one switch; we set them in lock-step
    here so the simpler UI stays in lock-step with the deeper model.
    """
    g = group_perms or {}
    see_brief = bool(g.get("can_see_brief"))
    return {
        "can_query_availability": bool(g.get("can_query_calendar")),
        "can_see_brief":          see_brief,
        "can_view_full_profile":  see_brief,
        "can_post_on_my_behalf":  bool(g.get("can_speak_for_group")),
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
    group_brief_content: str | None = None,
) -> None:
    """
    Invoke the target member's persona for an @-mention in a group room
    and post the reply as a `channel='agent'` row.

    The asker's permissions in the group decide what tools the target
    persona may call; we translate them to the existing external_permissions
    shape (see `_group_perms_to_external`).

    ``group_brief_content`` (phase 3a) is the trimmed body of the
    persona_groups.brief_doc — when present and ``can_see_brief`` is on,
    we inject it into the dispatch prefix so the persona has the SHARED
    team context (vs. just the target's own per-user brief). Pass None
    when no group brief exists or the asker doesn't have permission.

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
    # is what they asked." The can_see_brief hint below is belt-and-
    # suspenders: even though the brief body is already stripped from the
    # system prompt when permission is off, telling the LLM not to leak
    # equivalent details from memory keeps replies aligned.
    if asker_permissions.get("can_see_brief"):
        privacy_hint = (
            f"{asker_display_name} has been granted access to your principal's "
            f"private brief in this group. You may share specifics about what "
            f"they're working on, plans, and goals."
        )
    else:
        privacy_hint = (
            f"{asker_display_name} has NOT been granted access to your principal's "
            f"private brief. Keep your reply at the level of the public "
            f"description — don't share what they're working on, internal goals, "
            f"or other brief specifics. Decline politely if the question requires it."
        )
    # Group brief content (phase 3a) — when present, give the target
    # persona the SHARED context the team has co-authored. Truncated
    # to keep prompt size bounded; the cap is intentionally lower than
    # _LLM_BRIEF_CHAR_CAP used by the per-user brief because we're
    # appending on top of the existing prompt, not replacing it.
    brief_context = ""
    if group_brief_content and asker_permissions.get("can_see_brief"):
        snippet = group_brief_content.strip()
        if snippet:
            if len(snippet) > 2000:
                snippet = snippet[:2000].rstrip() + " …"
            brief_context = (
                "\n\n## Shared group brief — co-authored team context\n"
                "Use this for what THIS GROUP is working on. Treat it as the team's "
                "collective working memory (vs. your own per-user brief which is "
                "personal to your principal).\n"
                "---\n"
                f"{snippet}\n"
                "---"
            )

    prefixed_message = (
        f"[Group room context — you were @-mentioned by {asker_display_name} "
        f"in a private group. Reply as your principal's persona would, in 1–3 "
        f"sentences. The other group members will see your reply.\n"
        f"{privacy_hint}]"
        f"{brief_context}"
        f"\n\n{user_message}"
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


# ── group_context claim (cross-instance foundation) ────────────────────
# Each persona_group has a deterministic Ed25519 keypair derived from the
# developer seed + persona_groups.group_seed_index. Phase 2 same-instance
# dispatch doesn't need to sign anything (the API path is trusted), but
# cross-instance personas living on a different Zynd backend will. The
# build/verify helpers below are the boundary contract:
#
#   * sender:    `build_group_context_claim(group_id, asker_agent_id,
#                  asker_permissions, group_seed_index)` returns a
#                  base64 JSON blob the dispatching backend attaches to
#                  the A2A v3 envelope.
#   * receiver:  `verify_group_context_claim(claim, expected_group_id)`
#                  returns the parsed claim dict on success, raises on
#                  any failure (bad signature, expired ts, mismatched
#                  group_id, etc.). The caller is then responsible for
#                  membership-checking the asker_agent_id against the
#                  group's roster.
#
# The signed payload deliberately includes a `ts` (issued-at) and `exp`
# (expiry, default 5 minutes) so a captured claim can't be replayed
# indefinitely. The signature covers the canonical JSON encoding of the
# claim minus the signature field itself.

CLAIM_TTL_SECONDS = 300


def build_group_context_claim(
    *,
    group_id: str,
    group_seed_index: int,
    asker_agent_id: str,
    asker_user_id: str,
    asker_permissions: dict,
    developer_seed: bytes | None = None,
) -> str:
    """
    Build a base64-encoded, signed `group_context` claim.

    The receiver of an A2A v3 envelope inside a group attaches this string
    to the message; the target's backend verifies it before invoking its
    persona with group permissions.

    Phase 2 (same-instance) calls this only for tests / future-proofing —
    the dispatch path doesn't yet route through A2A. Wiring it into the
    real outbound A2A envelope is tracked in GROUPS.md.
    """
    from agent.zynd_identity import (
        derive_group_keypair,
        sign as _sign,
    )
    from agent.persona_manager import _load_developer_seed

    if developer_seed is None:
        developer_seed = _load_developer_seed()
    kp = derive_group_keypair(developer_seed, group_seed_index)

    now = int(time.time())
    payload = {
        "v": 1,
        "group_id": group_id,
        "asker_agent_id": asker_agent_id,
        "asker_user_id": asker_user_id,
        "asker_permissions": dict(asker_permissions or {}),
        "ts": now,
        "exp": now + CLAIM_TTL_SECONDS,
        "group_public_key": base64.b64encode(kp.public_key_bytes).decode(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["sig"] = _sign(kp.private_seed, canonical)
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()


def verify_group_context_claim(
    claim_b64: str,
    expected_group_id: str,
    *,
    developer_seed: bytes | None = None,
    group_seed_index: int | None = None,
) -> dict:
    """
    Decode + verify a `group_context` claim. Returns the parsed claim
    dict on success; raises ValueError with a specific reason on failure.

    Callers MUST additionally check that asker_agent_id is in the group's
    roster — verifying the signature only proves the claim was issued by
    the holder of the group seed, not that the asker named in the claim
    is actually a member.
    """
    from agent.zynd_identity import (
        derive_group_keypair,
        verify,
    )
    from agent.persona_manager import _load_developer_seed

    try:
        raw = base64.urlsafe_b64decode(claim_b64.encode())
        payload = json.loads(raw)
    except Exception as e:
        raise ValueError(f"malformed claim envelope: {e}") from e

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("unsupported claim version")
    if payload.get("group_id") != expected_group_id:
        raise ValueError("group_id mismatch")

    now = int(time.time())
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < now:
        raise ValueError("claim expired")
    ts = payload.get("ts")
    if not isinstance(ts, int) or ts > now + 60:
        # Allow 60s of clock skew but reject claims minted in the future.
        raise ValueError("claim issued in the future")

    sig = payload.pop("sig", None)
    if not sig:
        raise ValueError("missing signature")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    # Derive the expected group keypair. If the caller knows the index,
    # use it; otherwise the claim's `group_public_key` is the only hint —
    # but trusting that to look up the index would defeat the verification.
    # Cross-instance code paths MUST pass group_seed_index from the
    # receiver's local persona_groups row.
    if developer_seed is None:
        developer_seed = _load_developer_seed()
    if group_seed_index is None:
        raise ValueError("group_seed_index required for verification")
    kp = derive_group_keypair(developer_seed, group_seed_index)
    public_key_b64 = base64.b64encode(kp.public_key_bytes).decode()
    if not verify(public_key_b64, canonical, sig):
        raise ValueError("bad signature")

    # Re-attach for downstream consumers; the dict is otherwise the
    # signed payload (no sig, since we stripped it for canonicalization).
    payload["sig"] = sig
    return payload


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
