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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
      can_see_member_briefs → can_see_brief AND can_view_full_profile

    `can_speak_for_group` is INTENTIONALLY NOT mapped to `can_post_on_my_behalf`.
    Group context never grants broad write permissions on a teammate's accounts
    (calendar mutations, email sends, social posts). Scheduling in groups goes
    through the dedicated proposal/approval flow (Schedule pane → /api/groups/
    {id}/meetings) which writes a recipient-side approval row, not directly to
    anyone's calendar. The `can_speak_for_group` flag is for group-internal
    role gating (who can post system notes, edit rules, etc.) — not a
    cross-account write grant.

    `can_see_member_briefs` gates another member's private persona brief.
    Legacy rows may still carry `can_see_brief`; map that into the new key.
    The shared group brief is intentionally separate (`can_see_group_brief`)
    and is injected by this dispatcher, not by the target persona prompt.
    """
    g = group_perms or {}
    see_brief = bool(g.get("can_see_member_briefs", g.get("can_see_brief", False)))
    can_calendar = bool(g.get("can_query_calendar", False))
    return {
        "can_query_availability": can_calendar,
        "can_request_meetings":   can_calendar,
        "can_see_brief":          see_brief,
        "can_view_full_profile":  see_brief,
        "can_post_on_my_behalf":  False,
    }


def _can_see_member_briefs(group_perms: dict | None) -> bool:
    g = group_perms or {}
    return bool(g.get("can_see_member_briefs", g.get("can_see_brief", False)))


def _can_see_group_brief(group_perms: dict | None) -> bool:
    g = group_perms or {}
    return g.get("can_see_group_brief", True) is not False


# ── Constraints rendering ───────────────────────────────────────────────
_CONSTRAINT_LABEL = {
    "fact":  "Fact",
    "rule":  "Rule",
    "voice": "Voice",
}


def _format_constraints_block(constraints: list[dict] | None) -> str:
    """
    Render the group's constraint list as a prompt section the LLM can
    follow. Empty list → empty string (no section header). Constraints
    are grouped by kind so the model reads "Rules" / "Facts" / "Voice"
    as cohesive blocks rather than a flat list.
    """
    if not constraints:
        return ""
    by_kind: dict[str, list[str]] = {"rule": [], "fact": [], "voice": []}
    for c in constraints:
        kind = c.get("kind")
        text = (c.get("text") or "").strip()
        if not text or kind not in by_kind:
            continue
        by_kind[kind].append(text)

    if not any(by_kind.values()):
        return ""

    lines = ["\n\n## Group rules — must-follow guardrails for replies in this room"]
    # Order matters: rules first (hardest), then facts (context), then voice
    # (style). The model honors earlier-listed instructions more reliably.
    if by_kind["rule"]:
        lines.append("Rules (do NOT violate):")
        for t in by_kind["rule"]:
            lines.append(f"  - {t}")
    if by_kind["fact"]:
        lines.append("Shared facts the team has agreed on:")
        for t in by_kind["fact"]:
            lines.append(f"  - {t}")
    if by_kind["voice"]:
        lines.append("Voice / tone:")
        for t in by_kind["voice"]:
            lines.append(f"  - {t}")
    return "\n".join(lines)


# ── Dispatch ────────────────────────────────────────────────────────────
_GROUP_CONVERSATION_PREFIX = "group:"
_SHORT_FOLLOWUP_RE = re.compile(
    r"^\s*@?[A-Za-z0-9_\s-]{0,60}\s*(do it|answer|reply|tell (us|me)|go ahead|yes|yep|please do|share it)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def _conversation_id_for(group_id: str, target_user_id: str) -> str:
    """
    Stable per-(group, target persona) conversation id so each persona's
    in-group thread has its own history. Different askers in the same
    group share this thread for the same target — the persona sees the
    whole group conversation, not a fresh slate each turn.
    """
    return f"{_GROUP_CONVERSATION_PREFIX}{group_id}:{target_user_id}"


def _supabase():
    return config.get_supabase()


def _format_recent_group_context(group_id: str, current_message: str) -> str:
    """
    Give the mentioned persona the visible group context around this turn.

    The orchestrator conversation history is per target persona and in-memory,
    so after a deploy/restart or when the target wasn't mentioned in the
    previous turn, a short follow-up like "@Sahil do it" can look like a vague
    action request. The group message table is the canonical room transcript;
    include a compact recent slice so the persona can resolve "it" to the
    latest visible question.
    """
    try:
        sb = _supabase()
        rows = (
            sb.table("persona_group_messages")
            .select("sender_name, channel, content, created_at")
            .eq("group_id", group_id)
            .order("created_at", desc=True)
            .limit(8)
            .execute()
        )
        messages = list(reversed(rows.data or []))
    except Exception as e:
        logger.warning(f"[group-dispatch] couldn't load recent transcript for {group_id}: {e}")
        messages = []

    lines = ["\n\n## Recent visible group context"]
    if messages:
        for row in messages:
            sender = (row.get("sender_name") or "Someone").strip()
            channel = row.get("channel") or "human"
            content = (row.get("content") or "").strip().replace("\n", " ")
            if len(content) > 500:
                content = content[:500].rstrip() + " ..."
            lines.append(f"- {sender} ({channel}): {content}")
    else:
        lines.append(f"- Current message: {(current_message or '').strip()}")
    return "\n".join(lines)


def _group_reply_mode_block(*, target_display: str, asker_display_name: str, user_message: str) -> str:
    """Extra instructions that specialize external-mode behavior for group rooms."""
    followup_hint = ""
    if _SHORT_FOLLOWUP_RE.match(user_message or ""):
        followup_hint = (
            "\n- The current message is a short follow-up. Resolve words like "
            "\"it\" or \"do it\" from the recent group context, then answer that "
            "latest group question as the mentioned persona."
        )

    return f"""

## Group mention mode — override generic networking handoff behavior
This is a group room reply for @{target_display}, requested by {asker_display_name}.
Treat the @mention as a request for this persona to answer the group, not as a
request to connect the two humans.

Rules for this group reply:
- If the group asks about your principal, answer from the principal briefing and
  any allowed group/private brief context available in this prompt.
- If the group asks "what is {target_display} working on?", "what do they do?",
  or similar, answer directly with known facts. Do not say you'll pass it along.
- Do NOT use phrases like "I'll pass this along", "they'll follow up", "looping
  them in", or "connect with them" unless the human explicitly asks you to notify
  your principal outside the group.
- If the message is ambiguous but the recent group context contains a clear
  question, answer that question. If it is still ambiguous, ask one concise
  clarifying question in the group instead of escalating to the principal.
- Keep the visible reply as the agent representing {target_display}; do not
  impersonate the human.
{followup_hint}
"""


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
    group_constraints: list[dict] | None = None,
    time_zone: str | None = None,
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
    if _can_see_member_briefs(asker_permissions):
        privacy_hint = (
            f"{asker_display_name} is a trusted group member with full brief access. "
            f"Answer questions about your principal's work, focus, goals, and background "
            f"fully and specifically — draw on everything in the briefing above."
        )
    else:
        privacy_hint = (
            f"{asker_display_name} does not have brief access for this member. "
            f"Limit your reply to publicly visible information (name, title, general role). "
            f"Do not reveal current projects, internal goals, or detailed work context."
        )
    # Group brief content (phase 3a) — when present, give the target
    # persona the SHARED context the team has co-authored. Truncated
    # to keep prompt size bounded; the cap is intentionally lower than
    # _LLM_BRIEF_CHAR_CAP used by the per-user brief because we're
    # appending on top of the existing prompt, not replacing it.
    brief_context = ""
    if group_brief_content and _can_see_group_brief(asker_permissions):
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

    # Group constraints (phase 4) — hard guardrails every member's
    # persona must respect when speaking in this room. Three kinds:
    #   fact   → positive context the team has agreed on
    #   rule   → things to avoid / forbid
    #   voice  → style/tone guidance
    # Unlike the brief, these are NOT gated by can_see_brief — they're
    # the team's shared rules and apply to every member's persona in
    # the room regardless of the asker's permission set.
    constraints_block = _format_constraints_block(group_constraints)
    recent_group_context = _format_recent_group_context(group_id, user_message)
    group_reply_mode = _group_reply_mode_block(
        target_display=target_display,
        asker_display_name=asker_display_name,
        user_message=user_message,
    )

    try:
        tz = ZoneInfo(time_zone) if time_zone else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    now_local = datetime.now(tz)
    time_str = now_local.strftime("%A, %B %-d %Y %-I:%M %p") + (
        f" ({time_zone})" if time_zone and time_zone != "UTC" else " UTC"
    )

    prefixed_message = (
        f"[Group room context — you were @-mentioned by {asker_display_name} "
        f"in a private group. Reply as your principal's persona would, in 1–3 "
        f"sentences. The other group members will see your reply.\n"
        f"Current local time for the asker: {time_str}\n"
        f"{privacy_hint}]"
        f"{group_reply_mode}"
        f"{recent_group_context}"
        f"{constraints_block}"
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
            is_group_context=True,
            time_zone=time_zone,
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
        _post_system_note(group_id, f"{target_display}'s persona didn't have a response for that.")
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
