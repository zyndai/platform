"""Public "Working on" and "Can help with", derived from what memory knows now.

Both lists used to be written once by the onboarding LLM and never refreshed, so a card
kept saying what the person did when they signed up. The owner's approved memory facts
are fresher, so on every public read they come first and the stored list fills in behind
them.

The owner's editor loads /cards/mine and never goes through here, so derived items are
never saved back into the stored list. That is deliberate: if they were, an item the
owner deleted would come back from memory on the next save. Deleting a stored item
removes it; forgetting the memory fact removes that one; neither resurrects the other.

Precedence, memory first, then stored, case-insensitive dedupe:
  working_on     <- live `is_working_on` facts, newest approved first (they expire ~14 days
                    after approval, after which the stored list is all that is left)
  can_help_with  <- live `has_expertise_in` facts, highest confidence first
"""
from __future__ import annotations

from datetime import datetime

from models.card import AgentProfileCard
from services.card_view import fact_object, fact_predicate, live_facts

WORKING_ON_CAP = 4
CAN_HELP_WITH_CAP = 6


def _clean(items: list[str] | None) -> list[str]:
    return [i.strip() for i in (items or []) if isinstance(i, str) and i.strip()]


def merge_unique(memory_first: list[str], stored: list[str] | None, cap: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in [*_clean(memory_first), *_clean(stored)]:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= cap:
            break
    return out


def _confidence(fact: dict) -> float:
    try:
        return float(fact.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def derive_public_signals(card: AgentProfileCard, now: datetime | None = None) -> AgentProfileCard:
    """A copy of the card whose working_on / can_help_with reflect live memory facts.

    Returns the card unchanged when memory has nothing live for a list, so people who
    never connected an agent keep exactly what they had.
    """
    facts = live_facts(card.zynd_memory, now)
    update: dict = {}

    working = sorted(
        (f for f in facts if fact_predicate(f) == "is_working_on"),
        key=lambda f: str(f.get("approved_at") or ""),
        reverse=True,
    )
    if working:
        update["working_on"] = merge_unique(
            [fact_object(f) for f in working], card.working_on, WORKING_ON_CAP)

    expertise = sorted(
        (f for f in facts if fact_predicate(f) == "has_expertise_in"),
        key=_confidence,
        reverse=True,
    )
    if expertise:
        update["can_help_with"] = merge_unique(
            [fact_object(f) for f in expertise], card.can_help_with, CAN_HELP_WITH_CAP)

    return card.model_copy(update=update) if update else card
