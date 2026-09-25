"""
Network Introductions — finds the best person to connect with on the
Zynd network using memory context + network search.

When a user asks "who knows about X?" or "introduce me to someone who...",
this engine:
  1. Searches the Zynd network for relevant personas
  2. Cross-references with memory-layer for existing relationships
  3. Checks connection status (already connected? pending? blocked?)
  4. Ranks results by relevance + trust + mutual context
  5. Generates a natural introduction message
"""

from __future__ import annotations

import logging
from typing import Any

import config
from agent.memory_client import is_enabled

logger = logging.getLogger(__name__)


async def find_best_introduction(
    user_id: str,
    topic: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """Find the best person to introduce the user to on a given topic.

    Returns:
        dict with:
          - matches: ranked list of persona matches with scores + context
          - recommended: the top recommendation
          - intro_draft: a pre-written introduction message
    """
    result: dict[str, Any] = {
        "matches": [],
        "recommended": None,
        "intro_draft": None,
        "total_on_network": 0,
    }

    # 1. Search the Zynd network for personas matching the topic.
    network_results = await _search_network_personas(topic, top_k=10)
    if not network_results:
        return result

    result["total_on_network"] = len(network_results)

    # 2. Filter out the user's own persona.
    own_agent_id = await _get_own_agent_id(user_id)
    candidates = [
        p for p in network_results
        if p.get("entity_id", "").lower() != (own_agent_id or "").lower()
    ][:top_k * 2]

    if not candidates:
        return result

    # 3. For each candidate, enrich with context.
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        entity_id = candidate.get("entity_id", "")
        # match_score comes straight from search_zynd_personas — the actual
        # keyword-overlap count between `topic` and this candidate's bio.
        # Pass it through so ranking here reflects real topical relevance.
        score = await _score_candidate(
            user_id,
            entity_id,
            topic,
            raw_match_score=candidate.get("match_score", 0),
            target_name=candidate.get("name", ""),
            target_description=candidate.get("description", ""),
        )
        candidate["score"] = score["total"]
        candidate["score_breakdown"] = score
        candidate["connection_status"] = score.get("connection_status", "none")
        candidate["mutual_context"] = score.get("mutual_context", [])

        if candidate["connection_status"] in ("blocked", "revoked"):
            continue  # Skip blocked connections.

        scored.append(candidate)

    # 4. Sort by score descending.
    scored.sort(key=lambda c: c.get("score", 0), reverse=True)
    result["matches"] = scored[:top_k]

    # 5. Pick the top recommendation.
    if result["matches"]:
        top = result["matches"][0]
        result["recommended"] = {
            "name": top.get("name", "Unknown"),
            "entity_id": top.get("entity_id"),
            "reason": _format_recommendation_reason(top),
            "connection_status": top.get("connection_status", "none"),
        }

        # 6. Generate an intro draft.
        result["intro_draft"] = await _generate_intro_draft(
            user_id=user_id,
            target=top,
            topic=topic,
        )

    return result


async def get_network_overlap(
    user_id: str,
    target_agent_id: str,
) -> dict[str, Any]:
    """Find what two people have in common — shared interests, mutual
    connections, overlapping expertise areas.

    Useful when the user asks "what do [I/they] have in common with [person]?"
    """
    overlap: dict[str, Any] = {
        "shared_interests": [],
        "shared_connections": [],
        "common_topics": [],
        "suggested_icebreaker": None,
    }

    try:
        # Check connection status.
        conn_status = await _check_connection(user_id, target_agent_id)
        overlap["connection_status"] = conn_status

        # Resolve the target's actual profile once — used both as a real
        # search topic below (a raw agent_id is not natural language and
        # would never semantically match anything in memory) and as the
        # source of *their* interests (previously this pulled the caller's
        # own profile by mistake, so "shared interests" was really "the
        # user's interests compared against themselves").
        from mcp.tools.zynd_network import get_persona_profile
        target_profile_result = get_persona_profile(target_agent_id)
        target_name = (target_profile_result or {}).get("name") or ""
        target_description = (target_profile_result or {}).get("description") or ""
        target_profile_fields = (target_profile_result or {}).get("profile") or {}
        search_topic = f"{target_name} {target_description}".strip() or target_agent_id

        # Query memory-layer for context about both parties.
        if is_enabled():
            from agent.memory_client import get_context

            # What does the user's memory say about this person?
            user_ctx = await get_context(
                user_id=user_id,
                topic=search_topic,
                k=5,
                min_confidence=0.4,
            )
            if user_ctx and user_ctx.assertions:
                overlap["known_context"] = [
                    a.statement for a in user_ctx.assertions[:3]
                ]

            # What shared topics do they both care about?
            user_topics = await get_context(
                user_id=user_id,
                topic="interests expertise work industry projects",
                k=10,
                min_confidence=0.5,
            )

            profile = target_profile_fields

            # Match topics that overlap.
            if user_topics and user_topics.assertions and profile:
                user_keywords = set()
                for a in user_topics.assertions:
                    for word in (a.object or a.statement).lower().split():
                        if len(word) > 4:
                            user_keywords.add(word)

                target_interests = profile.get("interests", [])
                if isinstance(target_interests, str):
                    target_interests = [target_interests]
                elif not isinstance(target_interests, list):
                    target_interests = []

                for interest in target_interests:
                    interest_lower = interest.lower()
                    matches = [
                        w for w in user_keywords
                        if w in interest_lower or interest_lower in w
                    ]
                    if matches:
                        overlap["shared_interests"].append(interest)

        # Check shared connections.
        overlap["shared_connections"] = await _find_shared_connections(
            user_id, target_agent_id
        )

        # Generate an icebreaker.
        if overlap["shared_interests"] or overlap.get("known_context"):
            overlap["suggested_icebreaker"] = _build_icebreaker(overlap)

    except Exception as e:
        logger.debug("[intros] overlap calculation failed: %s", e)

    return overlap


# ── Internal scoring ──────────────────────────────────────────────────


async def _score_candidate(
    user_id: str,
    target_agent_id: str,
    topic: str,
    raw_match_score: int = 0,
    target_name: str = "",
    target_description: str = "",
) -> dict[str, Any]:
    """Score a candidate for introduction relevance.

    Args:
        raw_match_score: The keyword-overlap count from search_zynd_personas
            (how many of `topic`'s terms actually appear in this candidate's
            bio/tags) — the real topical-relevance signal. Without this, every
            candidate previously scored an identical hardcoded 0.5 "relevance"
            regardless of fit, so ranking was driven entirely by connection/
            mutual/trust bonuses — a candidate with zero relation to the topic
            but one mutual connection could outrank a strong topical match.
        target_name, target_description: From the search result row that
            produced this candidate — used as the memory-layer search topic
            below instead of the raw `target_agent_id`, which is not natural
            language and would never semantically match a stored assertion.
    """
    score: dict[str, Any] = {
        "total": 0.0,
        "relevance": 0.0,       # How well they match the topic
        "connection_bonus": 0.0, # Already connected?
        "mutual_bonus": 0.0,    # Shared connections?
        "trust_bonus": 0.0,     # Reputation/trust signals
        "connection_status": "none",
        "mutual_context": [],
    }

    # Relevance: 3+ overlapping keyword stems between the topic and this
    # candidate's bio/tags counts as a full-relevance match; scales linearly
    # below that. Zero overlap (e.g. a catchall browse, or a candidate that
    # only surfaced via connection/mutual signals) means zero relevance here.
    score["relevance"] = min(1.0, max(0, raw_match_score) / 3.0)

    # Connection check.
    conn = await _check_connection(user_id, target_agent_id)
    score["connection_status"] = conn
    if conn == "accepted":
        score["connection_bonus"] = 0.3  # Already connected = trust.
    elif conn == "pending":
        score["connection_bonus"] = 0.1  # Request already sent.
    elif conn == "none":
        score["connection_bonus"] = 0.0

    # Shared connections bonus.
    shared = await _find_shared_connections(user_id, target_agent_id)
    if shared:
        score["mutual_bonus"] = min(0.2, len(shared) * 0.05)
        score["mutual_context"] = shared

    # Trust bonus from memory: has the user mentioned this person before?
    if is_enabled():
        try:
            from agent.memory_client import get_context
            search_topic = f"{target_name} {target_description}".strip() or target_agent_id
            ctx = await get_context(
                user_id=user_id,
                topic=search_topic,
                k=3,
                min_confidence=0.5,
            )
            if ctx and ctx.assertions:
                # Weight by how confident/relevant the strongest match is,
                # rather than a flat bonus for "any assertion came back at
                # all" — a barely-relevant hit and a strong, confident one
                # about this specific person shouldn't move the score by
                # the same amount.
                top = ctx.assertions[0]
                score["trust_bonus"] = round(0.15 * top.confidence, 4)
        except Exception:
            pass

    score["total"] = (
        score["relevance"] * 0.5
        + score["connection_bonus"]
        + score["mutual_bonus"]
        + score["trust_bonus"]
    )

    return score


# ── Helpers ──────────────────────────────────────────────────────────


async def _search_network_personas(
    query: str, top_k: int = 10
) -> list[dict[str, Any]]:
    """Search the Zynd network for personas matching a query."""
    try:
        from mcp.tools.zynd_network import search_zynd_personas
        result = search_zynd_personas(query=query, top_k=top_k)
        if isinstance(result, dict):
            return result.get("results", []) or []
        return []
    except Exception as e:
        logger.debug("[intros] network search failed: %s", e)
        return []


async def _get_own_agent_id(user_id: str) -> str | None:
    """Get the user's own agent_id."""
    try:
        from agent.persona_manager import get_persona_status
        persona = get_persona_status(user_id)
        return persona.get("agent_id")
    except Exception:
        return None


async def _check_connection(
    user_id: str, target_agent_id: str
) -> str:
    """Check connection status between user and target.

    dm_threads' columns are initiator_id/receiver_id (not participant_id),
    and they store agent_ids, not Supabase user_ids — both mismatches
    silently made every lookup here fail and fall through to "unknown",
    even for pairs that really were connected.
    """
    try:
        own_agent_id = await _get_own_agent_id(user_id)
        if not own_agent_id:
            return "unknown"
        sb = config.get_supabase()
        for direction in [
            {"initiator_id": own_agent_id, "receiver_id": target_agent_id},
            {"initiator_id": target_agent_id, "receiver_id": own_agent_id},
        ]:
            rows = (
                sb.table("dm_threads")
                .select("status")
                .match(direction)
                .limit(1)
                .execute()
            )
            if rows.data:
                return rows.data[0].get("status", "none")
        return "none"
    except Exception:
        return "unknown"


async def _find_shared_connections(
    user_id: str, target_agent_id: str
) -> list[str]:
    """Find personas that both users are connected to.

    Same column-name/id-type mismatch as _check_connection — dm_threads
    uses initiator_id/receiver_id (agent_ids), not participant_id keyed by
    the raw Supabase user_id.
    """
    try:
        own_agent_id = await _get_own_agent_id(user_id)
        if not own_agent_id:
            return []
        sb = config.get_supabase()

        # Get user's connections.
        user_conns = (
            sb.table("dm_threads")
            .select("initiator_id, receiver_id")
            .or_(f"initiator_id.eq.{own_agent_id},receiver_id.eq.{own_agent_id}")
            .eq("status", "accepted")
            .execute()
        )

        user_peers: set[str] = set()
        for row in (user_conns.data or []):
            if row["initiator_id"] == own_agent_id:
                user_peers.add(row["receiver_id"])
            else:
                user_peers.add(row["initiator_id"])

        # Get target's connections.
        target_conns = (
            sb.table("dm_threads")
            .select("initiator_id, receiver_id")
            .or_(
                f"initiator_id.eq.{target_agent_id},"
                f"receiver_id.eq.{target_agent_id}"
            )
            .eq("status", "accepted")
            .execute()
        )

        target_peers: set[str] = set()
        for row in (target_conns.data or []):
            if row["initiator_id"] == target_agent_id:
                target_peers.add(row["receiver_id"])
            else:
                target_peers.add(row["initiator_id"])

        shared = list(user_peers & target_peers)
        return shared[:5]

    except Exception:
        return []


def _format_recommendation_reason(candidate: dict[str, Any]) -> str:
    """Format a human-readable reason for recommending this person.

    Leads with WHY they're topically relevant (the actual point of an
    "introduce me to someone who..." ask) before the social-graph context
    (connection/mutual status) — a reason built only from connection status
    and mutual connections doesn't answer "why this person" at all if
    there's zero topical basis for the match.
    """
    parts = []
    name = candidate.get("name", "This person")

    # Topical relevance first — this is the actual answer to "why them".
    match_reason = candidate.get("match_reason")
    if match_reason:
        parts.append(match_reason)
    else:
        description = (candidate.get("description") or "").strip()
        if description:
            parts.append(description[:140])

    score_breakdown = candidate.get("score_breakdown", {})
    conn = score_breakdown.get("connection_status", "none")
    if conn == "accepted":
        parts.append(f"you're already connected with {name}")
    elif conn == "pending":
        parts.append(f"a connection request is already pending with {name}")

    mutual = score_breakdown.get("mutual_context", [])
    if mutual:
        parts.append(f"you share {len(mutual)} mutual connection(s)")

    return (
        f"{name} — {'; '.join(parts)}"
        if parts
        else f"{name} — matches your search"
    )


async def _generate_intro_draft(
    user_id: str,
    target: dict[str, Any],
    topic: str,
) -> str | None:
    """Generate a draft introduction message."""
    try:
        from agent.persona_manager import get_persona_status
        persona = get_persona_status(user_id)
        principal_name = persona.get("name", "the user")
        target_name = target.get("name", "there")

        breakdown = target.get("score_breakdown", {})
        conn = breakdown.get("connection_status", "none")

        if conn == "accepted":
            return (
                f"You're already connected with {target_name}. "
                f"I can send them a message on your behalf — "
                f"just tell me what you'd like to say about {topic}."
            )

        if conn == "pending":
            return (
                f"Your connection request to {target_name} is already pending. "
                f"Once they accept, I can help you reach out about {topic}."
            )

        return (
            f"Want me to send {target_name} a connection request? "
            f"I can introduce you: \"Hi, I'm {principal_name}'s AI agent. "
            f"My principal is interested in {topic} and would love to connect.\""
        )

    except Exception:
        return None


def _build_icebreaker(overlap: dict[str, Any]) -> str:
    """Build an icebreaker message from shared context."""
    parts = []

    known = overlap.get("known_context", [])
    if known:
        parts.append(
            f"You've mentioned them before: {known[0][:100]}"
        )

    interests = overlap.get("shared_interests", [])
    if interests:
        parts.append(
            f"You both share interests in: {', '.join(interests[:3])}"
        )

    shared = overlap.get("shared_connections", [])
    if shared:
        parts.append(
            f"You have {len(shared)} mutual connection(s)"
        )

    return " • ".join(parts) if parts else "No obvious common ground yet."
