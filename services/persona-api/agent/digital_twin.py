"""
Digital Twin — makes the persona sound like you, know what you know,
and act on your behalf even when you're not there.

Capabilities:
  1. Style extraction — learn writing style from conversation history
  2. Personal knowledge Q&A — synthesize answers from your memory graph
  3. Async delegation — delegate tasks that the persona handles offline
  4. Style profile — persist and apply voice/style preferences
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import config
from agent.memory_client import get_context, is_enabled

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

# How many recent messages to analyze for style extraction.
STYLE_SAMPLE_SIZE = 20

# Minimum messages before style extraction produces useful output.
STYLE_MIN_SAMPLES = 8

# Cache TTL for style profiles (seconds).
STYLE_CACHE_TTL = 86400  # 24 hours


# ── Style Extraction ──────────────────────────────────────────────────


async def extract_writing_style(user_id: str) -> dict[str, Any]:
    """Analyze the user's conversation history and extract a style profile.

    Returns a dict with:
      - tone: casual | professional | witty | direct | warm
      - vocabulary_level: simple | moderate | technical
      - sentence_style: short | balanced | complex
      - common_phrases: list of frequently used expressions
      - formatting: emoji_use, punctuation_style, capitalization
      - confidence: how reliable this profile is (0-1)
      - sample_count: number of messages analyzed
    """
    messages = await _get_recent_user_messages(user_id, STYLE_SAMPLE_SIZE)
    if len(messages) < STYLE_MIN_SAMPLES:
        return {
            "tone": "professional",
            "vocabulary_level": "moderate",
            "sentence_style": "balanced",
            "common_phrases": [],
            "formatting": {"emoji_use": "minimal", "punctuation": "standard", "capitalization": "standard"},
            "confidence": 0.3,
            "sample_count": len(messages),
        }

    # Heuristic analysis — no LLM call needed for basic style extraction.
    style = _analyze_style_heuristics(messages)
    style["sample_count"] = len(messages)
    style["confidence"] = min(0.9, len(messages) / STYLE_SAMPLE_SIZE)

    # Persist to persona profile.
    await _save_style_profile(user_id, style)

    return style


def _analyze_style_heuristics(messages: list[str]) -> dict[str, Any]:
    """Extract writing style using fast heuristics (no LLM)."""
    total_chars = sum(len(m) for m in messages)
    total_words = sum(len(m.split()) for m in messages)

    # Average sentence length (rough — split on . ! ? \n)
    sentences = []
    for m in messages:
        for s in m.replace("!", ".").replace("?", ".").replace("\n", ".").split("."):
            stripped = s.strip()
            if stripped:
                sentences.append(stripped)
    avg_sentence_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)

    # Tone detection
    exclamation_ratio = sum(1 for m in messages if "!" in m) / len(messages)
    question_ratio = sum(1 for m in messages if "?" in m) / len(messages)
    emoji_count = sum(1 for m in messages for c in m if ord(c) > 127)
    caps_ratio = sum(1 for c in "".join(messages) if c.isupper()) / max(total_chars, 1)

    if emoji_count / max(len(messages), 1) > 0.5:
        tone = "warm"
    elif exclamation_ratio > 0.3 and question_ratio > 0.2:
        tone = "casual"
    elif avg_sentence_len < 8:
        tone = "direct"
    elif caps_ratio > 0.15:
        tone = "witty"
    else:
        tone = "professional"

    # Vocabulary level
    avg_word_len = total_chars / max(total_words, 1)
    if avg_word_len > 5.5:
        vocabulary_level = "technical"
    elif avg_word_len < 4.0:
        vocabulary_level = "simple"
    else:
        vocabulary_level = "moderate"

    # Sentence style
    if avg_sentence_len < 6:
        sentence_style = "short"
    elif avg_sentence_len > 18:
        sentence_style = "complex"
    else:
        sentence_style = "balanced"

    # Common phrases (words that appear in 30%+ of messages)
    word_freq: dict[str, int] = {}
    for m in messages:
        for word in m.lower().split():
            clean = word.strip(".,!?;:\"'()[]{}")
            if len(clean) > 3:
                word_freq[clean] = word_freq.get(clean, 0) + 1
    threshold = max(1, len(messages) * 0.3)
    common_phrases = [
        w for w, c in sorted(word_freq.items(), key=lambda x: -x[1])
        if c >= threshold
    ][:8]

    return {
        "tone": tone,
        "vocabulary_level": vocabulary_level,
        "sentence_style": sentence_style,
        "common_phrases": common_phrases,
        "formatting": {
            "emoji_use": "frequent" if emoji_count > len(messages) else "minimal",
            "punctuation": "emphatic" if exclamation_ratio > 0.3 else "standard",
            "capitalization": "standard",
        },
        "avg_sentence_words": round(avg_sentence_len, 1),
    }


def format_style_prompt(style: dict[str, Any]) -> str:
    """Convert a style profile into a system prompt section."""
    if style.get("confidence", 0) < 0.4:
        return ""  # Not enough data to be useful.

    lines = [
        "## Your Principal's Communication Style",
        "",
        "You have analyzed your principal's conversation history. When responding, "
        "match their natural communication patterns:",
        "",
        f"- **Tone**: {style.get('tone', 'professional')}",
        f"- **Vocabulary**: {style.get('vocabulary_level', 'moderate')}",
        f"- **Sentence style**: {style.get('sentence_style', 'balanced')} "
        f"(~{style.get('avg_sentence_words', '?')} words per sentence)",
    ]

    phrases = style.get("common_phrases", [])
    if phrases:
        lines.append(f"- **Common expressions**: {', '.join(phrases[:5])}")

    fmt = style.get("formatting", {})
    if fmt.get("emoji_use") == "frequent":
        lines.append("- **Emoji use**: Frequent — use emojis naturally")
    else:
        lines.append("- **Emoji use**: Minimal — use sparingly")

    lines.append("")
    lines.append(
        "Do NOT force this — if the style doesn't fit the context, default to "
        "your normal professional tone. The goal is to feel like the principal "
        "could have written it themselves."
    )
    lines.append("")

    return "\n".join(lines)


# ── Personal Knowledge Q&A ──────────────────────────────────────────


async def answer_like_me(
    user_id: str,
    question: str,
    conversation_id: str | None = None,
) -> str:
    """Answer a question using the user's memory graph and style.

    Queries memory-layer for relevant assertions, then uses the persona's
    LLM to synthesize a natural answer in the user's voice.

    Args:
        user_id: The user's Supabase UUID.
        question: Natural language question about the user's life, work, opinions.
        conversation_id: Optional chat context for the LLM.

    Returns:
        A natural-language answer synthesized from memory.
    """
    if not is_enabled():
        return "I don't have access to my memory store yet. Configure MEMORY_LAYER_JWT_SECRET to enable this."

    # 1. Query memory-layer for relevant facts.
    ctx = await get_context(
        user_id=user_id,
        topic=question,
        k=15,
        min_confidence=0.4,
    )

    if not ctx.assertions:
        return "I don't have enough context to answer that. Tell me more and I'll remember for next time."

    # 2. Load style profile.
    style = await _load_style_profile(user_id)

    # 3. Build a prompt for the LLM to synthesize.
    facts_text = "\n".join(
        f"- [{a.predicate}] {a.statement} (confidence: {a.confidence:.0%})"
        for a in ctx.assertions[:12]
    )

    style_block = format_style_prompt(style) if style.get("confidence", 0) >= 0.4 else ""

    synthesis_prompt = (
        f"You are answering a personal question about your principal. "
        f"Use ONLY the facts below to answer. If the facts are incomplete, "
        f"say so honestly — never make up information.\n\n"
        f"{style_block}\n"
        f"## Known Facts\n{facts_text}\n\n"
        f"## Question\n{question}\n\n"
        f"Write a natural response as if you're your principal's trusted AI. "
        f"Keep it concise (2-4 sentences unless the question demands detail)."
    )

    # 4. Run through the persona's LLM.
    return await _run_synthesis_prompt(user_id, synthesis_prompt, conversation_id)


# ── Async Delegation ──────────────────────────────────────────────────


async def delegate_task(
    user_id: str,
    task: str,
    target: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Delegate a task to the persona for async completion.

    The persona gathers relevant context from memory, drafts the output,
    and either sends it (if target specified) or saves it as a draft.
    The user gets a notification when it's done.

    Args:
        user_id: The user's Supabase UUID.
        task: Description of what to do ("Brief Sarah on Q3 numbers").
        target: Optional persona/email to send the output to.
        conversation_id: Optional chat context.

    Returns:
        Dict with status, draft content, and whether it was sent.
    """
    result: dict[str, Any] = {
        "status": "dispatched",
        "draft": None,
        "sent": False,
        "error": None,
    }

    try:
        # 1. Gather context from memory.
        ctx = await get_context(
            user_id=user_id,
            topic=task,
            k=15,
            min_confidence=0.4,
        )

        facts_text = "\n".join(
            f"- {a.statement}" for a in (ctx.assertions or [])[:10]
        ) if ctx and ctx.assertions else "(no relevant context found)"

        style = await _load_style_profile(user_id)

        # 2. Generate the output via LLM.
        style_block = format_style_prompt(style) if style.get("confidence", 0) >= 0.4 else ""

        delegation_prompt = (
            f"Your principal has delegated this task to you: \"{task}\"\n\n"
            f"{style_block}\n"
            f"## Relevant Context from Memory\n{facts_text}\n\n"
            f"Complete the task. Output the final deliverable — an email draft, "
            f"meeting brief, summary, or whatever was asked for. "
            f"Lead directly with the output, no preamble."
        )

        draft = await _run_synthesis_prompt(user_id, delegation_prompt, conversation_id)
        result["draft"] = draft

        # 3. If a target was specified, attempt delivery.
        if target:
            success = await _deliver_to_target(user_id, target, task, draft)
            result["sent"] = success
            result["status"] = "completed" if success else "drafted"
        else:
            result["status"] = "drafted"

    except Exception as e:
        logger.exception("[twin] delegation failed for %s", user_id)
        result["status"] = "failed"
        result["error"] = str(e)[:200]

    return result


# ── Public-Facing Twin ────────────────────────────────────────────────


async def generate_public_profile(user_id: str) -> dict[str, Any]:
    """Generate a public-facing profile card for the user's digital twin.

    Combines persona profile + memory-layer facts to create a shareable
    summary that represents the user to strangers on the Zynd network.
    """
    profile: dict[str, Any] = {
        "name": None,
        "bio": None,
        "highlights": [],
        "interests": [],
        "top_facts": [],
        "style_summary": None,
    }

    try:
        # Persona profile.
        from agent.persona_manager import get_persona_status
        persona = get_persona_status(user_id)
        profile["name"] = persona.get("name")
        profile["bio"] = persona.get("description") or persona.get("profile", {}).get("title", "")

        # Memory-layer facts.
        if is_enabled():
            ctx = await get_context(
                user_id=user_id,
                topic="work role interests expertise projects achievements",
                k=12,
                min_confidence=0.6,
            )
            if ctx and ctx.assertions:
                profile["top_facts"] = [
                    a.statement[:150] for a in ctx.assertions[:6]
                ]
                profile["interests"] = [
                    a.object for a in ctx.assertions
                    if a.predicate in ("is_interested_in", "is_learning", "is_reading")
                ][:5]

        # Style summary.
        style = await _load_style_profile(user_id)
        if style.get("confidence", 0) >= 0.5:
            profile["style_summary"] = (
                f"{style.get('tone', 'professional').title()} tone, "
                f"{style.get('sentence_style', 'balanced')} sentences"
            )

        # Highlights (combine top facts + style).
        profile["highlights"] = profile["top_facts"][:4]

    except Exception as e:
        logger.debug("[twin] public profile generation failed for %s: %s", user_id, e)

    return profile


# ── Internal helpers ──────────────────────────────────────────────────


async def _get_recent_user_messages(
    user_id: str, limit: int = STYLE_SAMPLE_SIZE
) -> list[str]:
    """Get recent user messages from chat history."""
    try:
        sb = config.get_supabase()
        rows = (
            sb.table("chat_messages")
            .select("content")
            .eq("user_id", user_id)
            .eq("role", "user")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [
            r.get("content", "") for r in (rows.data or [])
            if r.get("content") and len(r.get("content", "")) > 10
        ]
    except Exception:
        return []


def _style_cache_key(user_id: str) -> str:
    return f"style_profile:{user_id}"


async def _load_style_profile(user_id: str) -> dict[str, Any]:
    """Load the user's style profile from persona_agents.profile."""
    try:
        from agent.persona_manager import get_persona_status
        persona = get_persona_status(user_id)
        profile = persona.get("profile") or {}
        style_data = profile.get("writing_style") if isinstance(profile, dict) else None
        if style_data and isinstance(style_data, dict):
            return style_data
    except Exception:
        pass
    return {"confidence": 0.0}


async def _save_style_profile(user_id: str, style: dict[str, Any]) -> None:
    """Persist the style profile to the persona's profile JSONB."""
    try:
        sb = config.get_supabase()
        from agent.persona_manager import get_persona_status
        persona = get_persona_status(user_id)
        current_profile = persona.get("profile") or {}
        if not isinstance(current_profile, dict):
            current_profile = {}
        current_profile["writing_style"] = style
        current_profile["writing_style_updated_at"] = datetime.now(timezone.utc).isoformat()

        sb.table("persona_agents").update({
            "profile": current_profile,
        }).eq("user_id", user_id).execute()
    except Exception as e:
        logger.debug("[twin] style save failed for %s: %s", user_id, e)


async def _run_synthesis_prompt(
    user_id: str,
    prompt: str,
    conversation_id: str | None = None,
) -> str:
    """Run a synthesis prompt through the persona's LLM provider."""
    try:
        from agent.orchestrator import _get_provider

        provider = _get_provider()
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Complete the task."},
        ]

        import asyncio
        text, _ = await asyncio.to_thread(provider.chat_with_tools, messages, [])
        return (text or "").strip()
    except Exception as e:
        logger.warning("[twin] synthesis LLM call failed: %s", e)
        return f"Failed to generate response: {str(e)[:100]}"


async def _deliver_to_target(
    user_id: str,
    target: str,
    task: str,
    content: str,
) -> bool:
    """Deliver a delegation result to a target persona."""
    try:
        from agent.orchestrator import handle_user_message
        # Route through the existing persona chat — the LLM will use
        # message_zynd_agent or send_gmail_email depending on the target.
        result = await handle_user_message(
            user_id=user_id,
            message=(
                f"Deliver this to {target}:\n\n"
                f"Task: {task}\n\n"
                f"Output:\n{content}"
            ),
            is_external=False,
        )
        return bool(result.get("reply"))
    except Exception as e:
        logger.warning("[twin] delivery to %s failed: %s", target, e)
        return False
