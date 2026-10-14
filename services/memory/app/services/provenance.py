"""Where a card fact came from, in words a person would use.

Pure helpers (no DB). The origin of a fact is the `source_system` of the trace chunk that
evidenced it when there is one, because approving a fact rewrites the assertion's own
`source_system` to 'user_confirmed' and would otherwise erase that it was an agent's
report. A fact with no chunk (declared in the editor, confirmed by the user) falls back
to the assertion's `source_system`.

Public (card, agents): only the coarse label. The evidence excerpt is the person's own
words and is returned only to the owner (see `evidence_excerpt`).
"""
from __future__ import annotations

# label -> short human phrase for the editor chip
PROVENANCE_LABELS: dict[str, str] = {
    "you": "You added this",
    "agent": "Reported by your coding agent",
    "profile": "From your profile import",
    "chat": "Noticed in your AI chats",
    "import": "From a memory import",
    "inferred": "Inferred",
}

_BY_SYSTEM: dict[str, str] = {
    "user_confirmed": "you",
    "cards_mcp": "agent",
    "persona_seeded": "profile",
    "claude": "chat",
    "chatgpt": "chat",
    "import": "import",
}

EVIDENCE_MAX_CHARS = 160


def provenance_for(source_system: str | None, source: str | None = None,
                   chunk_source_system: str | None = None) -> str:
    """Coarse origin label for one fact.

    chunk_source_system wins when present (the original evidence); otherwise the
    assertion's own source_system; a declared fact with an unknown system is "you".
    """
    for system in (chunk_source_system, source_system):
        label = _BY_SYSTEM.get((system or "").strip().lower())
        if label:
            return label
    if (source or "").strip().lower() == "declared":
        return "you"
    return "inferred"


def evidence_excerpt(raw_text: str | None) -> str | None:
    """The person's own sentence behind a fact, clipped. Owner-only."""
    text = " ".join((raw_text or "").split())
    if not text:
        return None
    if len(text) <= EVIDENCE_MAX_CHARS:
        return text
    return text[: EVIDENCE_MAX_CHARS - 1].rstrip() + "…"
