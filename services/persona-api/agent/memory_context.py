"""
Memory Context Helpers — formats memory-layer assertions for LLM prompts
and prepares conversation turns for ingestion.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.memory_client import (
    MemoryAssertion,
    MemoryContext,
    IngestResult,
    get_context,
    ingest_turns,
)

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────

# How many messages from conversation history to ingest (avoids re-ingesting
# the entire history every turn — just the new exchange is enough).
MAX_TURNS_PER_INGEST = 4

# Topic extraction prompt suffix — appended to user message for semantic search.
# Short so the embedding is tight.
TOPIC_EXTRACTION_PROMPT = (
    "Extract a concise topic phrase (≤80 chars) from the following user message "
    "for semantic memory search. Return ONLY the phrase, no explanation."
)


# ─── Context injection ──────────────────────────────────────────────


def _predicate_label(predicate: str) -> str:
    """Human-readable label for an assertion predicate."""
    labels: dict[str, str] = {
        "is_working_on": "Working on",
        "is_interested_in": "Interested in",
        "is_learning": "Learning",
        "has_goal": "Goal",
        "has_skill": "Skill",
        "uses_tool": "Uses",
        "is_affiliated_with": "Affiliated with",
        "works_at": "Works at",
        "is_studying_at": "Studying at",
        "lives_in": "Lives in",
        "has_role": "Role",
        "prefers": "Prefers",
        "dislikes": "Dislikes",
        "is_reading": "Reading",
        "built": "Built",
        "knows": "Knows",
    }
    return labels.get(predicate, predicate)


def _confidence_bar(confidence: float, width: int = 5) -> str:
    """A visual confidence bar like ████░."""
    filled = max(1, int(confidence * width))
    return "█" * filled + "░" * (width - filled)


def format_context_for_prompt(context: MemoryContext) -> str:
    """Convert memory assertions into a compact prompt section.

    The output is structured as bullet points grouped by predicate,
    with confidence bars so the LLM knows how much to trust each fact.
    """
    if not context.assertions:
        return ""

    # Group by predicate for readability
    by_predicate: dict[str, list[MemoryAssertion]] = {}
    for a in context.assertions:
        by_predicate.setdefault(a.predicate, []).append(a)

    lines = [
        "## Personal Memory (from previous conversations)",
        "",
        "The following facts about the principal were extracted from prior conversations. "
        "Confidence bars (████░) indicate how certain these facts are. "
        "Use these to personalise your responses — reference them naturally, "
        "never recite them as a list.",
        "",
    ]

    for predicate, assertions in by_predicate.items():
        label = _predicate_label(predicate)
        lines.append(f"### {label}")
        for a in assertions:
            bar = _confidence_bar(a.confidence)
            obj = a.object if a.object else a.statement
            lines.append(f"- {bar} {obj}")
        lines.append("")

    return "\n".join(lines)


def format_context_as_list(context: MemoryContext) -> str:
    """Flat bullet list of assertions — used when space is tight."""
    if not context.assertions:
        return ""

    lines = ["", "## What I remember about you", ""]
    for a in context.assertions:
        obj = a.object if a.object else a.statement
        lines.append(f"- {_predicate_label(a.predicate)}: {obj}")
    return "\n".join(lines)


# ─── Topic extraction ───────────────────────────────────────────────


def extract_search_topic(message: str) -> str:
    """Extract a search topic from the user's last message.

    Simple heuristic: use the message directly if it's short;
    otherwise take the first sentence.
    """
    msg = message.strip()
    if len(msg) <= 80:
        return msg
    # Take the first sentence or first 80 chars, whichever is longer.
    for delimiter in (". ", "? ", "! ", "\n"):
        if delimiter in msg:
            first = msg.split(delimiter)[0]
            if 20 <= len(first) <= 80:
                return first
    return msg[:80]


# ─── Ingestion helpers ──────────────────────────────────────────────


def prepare_turns_for_ingest(
    conversation_history: list[dict[str, Any]],
    user_message: str,
    assistant_reply: str,
) -> list[dict[str, Any]]:
    """Prepare conversation turns for memory-layer ingestion.

    Takes the last few turns from conversation history plus the new exchange,
    deduplicates by content hash (the memory layer handles exact dedup at
    ingest time too, but this avoids sending obviously redundant turns),
    and returns a compact list suitable for the /ingest endpoint.

    Args:
        conversation_history: The in-memory conversation (list of role/content dicts).
        user_message: The user's latest message.
        assistant_reply: The assistant's latest reply.

    Returns:
        List of {role, content} dicts ready for memory_client.ingest_turns().
    """
    turns: list[dict[str, str]] = []

    # Take the last N turns from history (excluding the current exchange).
    recent = conversation_history[-MAX_TURNS_PER_INGEST:] if conversation_history else []

    # Build a set of short-content hashes to skip obvious duplicates.
    seen: set[str] = set()
    for turn in recent:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role not in ("user", "assistant"):
            continue
        if not content or len(content) < 10:
            continue
        short_hash = f"{role}:{content[:60]}"
        if short_hash in seen:
            continue
        seen.add(short_hash)
        turns.append({"role": role, "content": content[:4000]})  # cap for safety

    # Add the new exchange if not already in history.
    for role, content in [("user", user_message), ("assistant", assistant_reply)]:
        if not content or len(content) < 10:
            continue
        short_hash = f"{role}:{content[:60]}"
        if short_hash in seen:
            continue
        seen.add(short_hash)
        turns.append({"role": role, "content": content[:4000]})

    return turns


# ─── High-level orchestrator hooks ───────────────────────────────────


async def load_memory_context(user_id: str, user_message: str) -> MemoryContext:
    """Load relevant memory context for a user's message.

    Called at the start of every user chat turn. Extracts a search topic
    from the user's message, queries the memory layer, and returns a
    MemoryContext ready for prompt injection.
    """
    topic = extract_search_topic(user_message)
    context = await get_context(user_id=user_id, topic=topic)
    if context.error:
        logger.debug("[memory] context load skipped (error=%s)", context.error)
    elif context.assertions:
        logger.info(
            "[memory] loaded %d assertions for user=%s topic=%r",
            len(context.assertions), user_id, topic[:40],
        )
    return context


async def ingest_conversation(
    user_id: str,
    conversation_history: list[dict[str, Any]],
    user_message: str,
    assistant_reply: str,
    conversation_id: str | None,
) -> IngestResult:
    """Ingest the latest conversation exchange into the memory layer.

    Called after every user chat turn (fire-and-forget — errors are logged
    but never block the response to the user).
    """
    turns = prepare_turns_for_ingest(conversation_history, user_message, assistant_reply)
    if not turns:
        return IngestResult()

    result = await ingest_turns(
        user_id=user_id,
        turns=turns,
        conversation_id=conversation_id,
    )
    return result
