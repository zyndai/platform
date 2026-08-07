"""
Digital Twin MCP Tools — persona-facing tools for style cloning,
personal knowledge Q&A, and async delegation.
"""

from __future__ import annotations

from agent.memory_client import is_enabled


async def answer_like_me(user_id: str, question: str) -> str:
    """Answer a personal question using the principal's memory graph.

    Use this when the user asks questions about themselves that require
    synthesizing information from past conversations, like:
      - "What was I working on in March?"
      - "What are my main priorities right now?"
      - "What do I know about AI agents?"
      - "Summarize what I've told you about my startup"
      - "What's my opinion on remote work?"

    This tool queries the memory graph for relevant facts and synthesizes
    a natural answer in the principal's communication style.

    Args:
        question: A clear, specific question about the principal's life,
                  work, opinions, or knowledge.
    """
    if not is_enabled():
        return "Memory layer not configured. Set MEMORY_LAYER_JWT_SECRET to enable personal knowledge Q&A."

    from agent.digital_twin import answer_like_me as _answer

    return await _answer(user_id=user_id, question=question)


async def delegate_to_my_persona(
    user_id: str,
    task: str,
    target: str | None = None,
) -> str:
    """Delegate a task for the persona to complete asynchronously.

    Use this when the user wants you to do something that takes multiple
    steps or needs offline execution:
      - "Brief Sarah on the Q3 numbers and send it to her"
      - "Draft an email updating investors on our progress"
      - "Research competitors and compile a summary for me"
      - "Write a blog post about our launch and save it as a draft"

    The persona will:
      1. Gather relevant context from memory
      2. Draft the output in the principal's style
      3. Deliver to the target (if specified) or save as a draft

    Args:
        task: Clear description of what to produce.
        target: Optional recipient — a persona name, email, or "save as draft".
    """
    if not is_enabled():
        return "Memory layer not configured. Set MEMORY_LAYER_JWT_SECRET to enable delegation."

    from agent.digital_twin import delegate_task

    result = await delegate_task(user_id=user_id, task=task, target=target)

    if result["status"] == "failed":
        return f"Delegation failed: {result.get('error', 'unknown error')}"

    draft = result.get("draft", "")
    response = ""

    if result.get("sent"):
        response = f"✅ Task completed and delivered to {target}.\n\n"
    else:
        response = "✅ Task completed. Here's the draft:\n\n"

    if draft:
        response += draft[:3000]  # Cap for display

    return response


async def what_do_i_really_know_about(
    user_id: str,
    topic: str,
) -> str:
    """Deep-dive into the principal's memory graph on a specific topic.

    More comprehensive than 'what_do_you_know_about_me' — this dives
    into the full memory graph, groups facts by category, and highlights
    contradictions or gaps.

    Use when the user asks:
      - "Tell me everything you know about my health goals"
      - "What's the full picture on my career history?"
      - "Show me everything you remember about Project Phoenix"

    Args:
        topic: A specific topic to deep-dive into.
    """
    if not is_enabled():
        return "Memory layer not configured."

    from agent.memory_client import get_context
    from agent.memory_context import confidence_bar

    ctx = await get_context(
        user_id=user_id,
        topic=topic,
        k=30,
        min_confidence=0.3,  # Lower threshold for deep-dive
    )

    if not ctx or not ctx.assertions:
        return f"I don't have any recorded facts about '{topic}' yet."

    # Group by predicate for structured presentation.
    by_predicate: dict[str, list] = {}
    for a in ctx.assertions:
        predicate_label = {
            "is_working_on": "💼 Working on",
            "has_goal": "🎯 Goals",
            "is_interested_in": "💡 Interests",
            "knows": "🧠 Knowledge",
            "prefers": "👍 Preferences",
            "dislikes": "👎 Dislikes",
            "built": "🛠 Built",
            "is_learning": "📚 Learning",
            "works_at": "🏢 Work",
            "lives_in": "🏠 Location",
            "has_role": "👤 Role",
            "has_skill": "⚡ Skills",
            "is_reading": "📖 Reading",
        }.get(a.predicate, f"📌 {a.predicate}")

        by_predicate.setdefault(predicate_label, []).append(a)

    lines = [f"## Deep Dive: {topic}", ""]

    for label, assertions in by_predicate.items():
        lines.append(f"### {label}")
        for a in assertions:
            obj = a.object if a.object else a.statement
            lines.append(f"- {confidence_bar(a.confidence)} {obj}")
        lines.append("")

    # Flag contradictions.
    contradictions = []
    for label, assertions in by_predicate.items():
        values = [a.object or a.statement for a in assertions]
        unique = list(set(values))
        if len(unique) >= 2:
            contradictions.append((label, unique))

    if contradictions:
        lines.append("### ⚠️ Potential Contradictions")
        lines.append("I have conflicting information on these topics:")
        for label, vals in contradictions:
            lines.append(f"- **{label}**: " + " vs ".join(f'"{v[:60]}"' for v in vals[:3]))
        lines.append("")

    lines.append(f"*Total facts on this topic: {len(ctx.assertions)}*")

    return "\n".join(lines)


async def refresh_my_style(user_id: str) -> str:
    """Refresh the persona's understanding of the principal's communication style.

    Analyzes recent conversation history and updates the style profile.
    Use when the user notices the persona doesn't sound like them, or
    after a long period of conversation to keep the style fresh.

    No arguments needed — operates on the authenticated user.
    """
    from agent.digital_twin import extract_writing_style

    style = await extract_writing_style(user_id)

    if style.get("confidence", 0) < 0.4:
        return (
            f"I analyzed your recent messages but don't have enough data yet "
            f"({style.get('sample_count', 0)} messages found, need at least 8 "
            f"substantial ones). Keep chatting and I'll learn your style naturally."
        )

    return (
        f"✅ Style profile updated from {style.get('sample_count', 0)} recent messages.\n\n"
        f"- **Tone**: {style.get('tone', '?')}\n"
        f"- **Vocabulary**: {style.get('vocabulary_level', '?')}\n"
        f"- **Sentences**: {style.get('sentence_style', '?')} "
        f"(~{style.get('avg_sentence_words', '?')} words)\n"
        f"- **Confidence**: {style.get('confidence', 0):.0%}\n"
        f"- **Common phrases**: {', '.join(style.get('common_phrases', [])[:5]) or 'none yet'}\n\n"
        f"I'll use this to match your natural communication patterns."
    )
