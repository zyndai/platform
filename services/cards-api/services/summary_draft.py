"""Draft an About paragraph from what the owner has approved in memory.

The About text used to come from the LinkedIn import at signup and never changed. This
builds a *proposal* from the owner's current public facts. It is never saved here: the
owner previews it and decides in the editor, so a model can never silently rewrite how
someone describes themselves.

Only facts the owner approved for the public card go into the prompt (the same live
facts the public card shows). Evidence sentences, private memory and unapproved
suggestions never reach the model.
"""
from __future__ import annotations

import re
from datetime import datetime

import config
from models.card import AgentProfileCard
from services.card_view import fact_object, fact_predicate, live_facts

MAX_DRAFT_CHARS = 700
MAX_FACTS_PER_SECTION = 6

# Section label -> predicates, in the order they read best in a bio.
_SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("Building", ("is_building",)),
    ("Working on right now", ("is_working_on",)),
    ("Expert in", ("has_expertise_in",)),
    ("Learning", ("is_learning",)),
    ("Tools they use", ("uses_tool",)),
]

SYSTEM = (
    "You write the About paragraph for a professional profile card, in the third person, "
    "from the facts provided. Focus on substantive work, expertise and current roles; "
    "omit incidental activity and tool names unless they define the person's work. "
    "Do not try to mention every fact. Rules: two or three plain sentences. Use only the facts "
    "given; do not add employers, numbers, years or claims that are not there. No hype "
    "or filler words (passionate, seasoned, cutting-edge, leverage, innovative, "
    "world-class). Do not mention that facts were provided. No bullet points, no quotes, "
    "no links, no email addresses. Return only the paragraph."
)

_BANNED = re.compile(r"https?://|www\.|@\w|\bpassionate\b|\bseasoned\b|\bcutting-edge\b", re.I)


def facts_by_section(card: AgentProfileCard, now: datetime | None = None) -> dict[str, list[str]]:
    """The owner's live public facts grouped for the prompt. Private memory is not here."""
    live = live_facts(card.zynd_memory, now)
    out: dict[str, list[str]] = {}
    for label, predicates in _SECTIONS:
        names: list[str] = []
        for fact in live:
            if fact_predicate(fact) in predicates:
                name = fact_object(fact)
                if name and name.lower() not in {n.lower() for n in names}:
                    names.append(name)
        if names:
            out[label] = names[:MAX_FACTS_PER_SECTION]
    return out


def based_on(sections: dict[str, list[str]]) -> list[str]:
    """Human-readable list shown next to the draft so the owner sees what it came from."""
    return [f"{label}: {', '.join(names)}" for label, names in sections.items()]


def build_messages(card: AgentProfileCard, sections: dict[str, list[str]]) -> list[dict]:
    lines = [f"Name: {card.identity.name}"]
    if card.identity.headline:
        lines.append(f"Headline: {card.identity.headline}")
    current = [j for j in (card.work_experience or []) if isinstance(j, dict)
               and not (j.get("end_date") or "").strip()][:3]
    for job in current:
        title, company = (job.get("title") or "").strip(), (job.get("company") or "").strip()
        if title and company:
            lines.append(f"Current role: {title} at {company}")
    for label, names in sections.items():
        lines.append(f"{label}: {', '.join(names)}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


class DraftRejected(ValueError):
    """The model's output was unusable; nothing is shown to the owner."""


def clean_draft(text: str | None) -> str:
    """Normalise the model's paragraph and refuse anything that is not a plain bio."""
    draft = " ".join((text or "").strip().strip("\"'`").split())
    if not draft:
        raise DraftRejected("empty draft")
    if len(draft) > MAX_DRAFT_CHARS:
        raise DraftRejected("draft too long")
    if _BANNED.search(draft):
        raise DraftRejected("draft contains a link, address or filler wording")
    return draft


def generate_summary_draft(card: AgentProfileCard, sections: dict[str, list[str]], client=None) -> str:
    client = client or config.get_llm_client()
    resp = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        temperature=0.3,
        messages=build_messages(card, sections),
    )
    if not resp.choices:
        raise DraftRejected("no response")
    return clean_draft(resp.choices[0].message.content)
