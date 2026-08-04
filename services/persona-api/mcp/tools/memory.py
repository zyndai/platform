"""
Memory MCP Tools — persona-facing tools for long-term memory.

These tools let a persona's LLM:
  - Query what it knows about its principal
  - Explicitly remember or forget facts
  - Cross-reference past conversations
"""

from __future__ import annotations

import config
from agent.memory_client import (
    get_context,
    confirm_fact,
    forget_fact,
    MemoryContext,
)
from agent.memory_context import format_context_as_list


async def what_do_you_know_about_me(user_id: str, topic: str | None = None) -> str:
    """Query the persona's long-term memory about the principal.

    Use this when the user asks questions like:
      - "What do you remember about me?"
      - "What do I have going on this week?"
      - "Have I talked about X before?"
      - "What are my goals?"

    Args:
        topic: Keyword or short phrase to filter memories (e.g. "startup", "health", "travel").
               Omit to return recent memories across all topics.
    """
    if not config.MEMORY_LAYER_JWT_SECRET:
        return "Memory layer is not configured. Ask your admin to set MEMORY_LAYER_JWT_SECRET."

    search_topic = topic or "recent activities interests goals preferences"
    context = await get_context(
        user_id=user_id,
        topic=search_topic,
        k=25,
        min_confidence=0.4,
    )

    if context.error:
        return f"Couldn't reach my memory store ({context.error}). I'll work with what I know from this conversation."

    if not context.assertions:
        return "I don't have any recorded memories about that topic yet. Tell me about yourself and I'll remember for next time!"

    return format_context_as_list(context)


async def remember_this(user_id: str, fact: str) -> str:
    """Persist a single fact the user explicitly wants remembered.

    Use this when the user says things like:
      - "Remember that I'm allergic to peanuts"
      - "Make a note: I prefer morning meetings"
      - "Don't forget my wife's birthday is June 12th"

    Args:
        fact: The exact fact to remember, phrased as a statement
              (e.g. "The principal is allergic to peanuts").
    """
    if not config.MEMORY_LAYER_JWT_SECRET:
        return "Memory layer is not configured. Ask your admin to set MEMORY_LAYER_JWT_SECRET."

    from agent.memory_client import ingest_turns

    result = await ingest_turns(
        user_id=user_id,
        turns=[{"role": "user", "content": fact}],
        source_system="agent-persona-remember",
    )

    if result.error:
        return f"Couldn't save that fact ({result.error})."

    return f"Got it — I've saved: \"{fact}\""


async def forget_this(user_id: str, fact_statement: str) -> str:
    """Remove or decay a fact the user wants forgotten.

    Use when the user says things like:
      - "Forget what I said about quitting my job"
      - "I don't actually live in SF anymore"
      - "Remove that from my memory"

    Args:
        fact_statement: A substring or full statement matching a stored fact
                       to forget.
    """
    if not config.MEMORY_LAYER_JWT_SECRET:
        return "Memory layer is not configured."

    ok = await forget_fact(user_id, fact_statement)
    if not ok:
        return "I couldn't find that fact in my memory, or the memory layer is unreachable."
    return f"Forgotten — I've removed \"{fact_statement}\" from my memory."
