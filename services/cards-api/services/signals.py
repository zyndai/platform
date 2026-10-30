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
  working_on_updated_at <- the stored stamp (cards migration 0035), moved up to the newest live
                    `is_working_on` approval: the list is as fresh as its freshest source
  can_help_with  <- live `has_expertise_in` facts, highest confidence first
  exploring      <- the owner's browser clips (services/companion.py) from the last
                    EXPLORING_VISIBLE_DAYS days; older ones stay stored but stop showing
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models.card import AgentProfileCard
from services.card_view import _parse_ts, fact_object, fact_predicate, live_facts

WORKING_ON_CAP = 4
CAN_HELP_WITH_CAP = 6
EXPLORING_VISIBLE_DAYS = 30   # "currently" should not outlive the person


def _clean(items: list[str] | None) -> list[str]:
    return [i.strip() for i in (items or []) if isinstance(i, str) and i.strip()]


def _added_after(added_at: str, cutoff: datetime) -> bool:
    try:
        when = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)) > cutoff


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


def _newest_approval(facts: list[dict], now: datetime) -> datetime | None:
    """Latest approved_at among the facts, never later than now (a clock-skewed approval must not
    keep a list looking fresh forever)."""
    stamps = [t for f in facts if (t := _parse_ts(f.get("approved_at")))]
    return min(max(stamps), now) if stamps else None


def derive_public_signals(card: AgentProfileCard, now: datetime | None = None) -> AgentProfileCard:
    """A copy of the card whose working_on / can_help_with reflect live memory facts.

    Returns the card unchanged when memory has nothing live for a list, so people who
    never connected an agent keep exactly what they had.
    """
    now = now or datetime.now(timezone.utc)
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
        stamp = _newest_approval(working, now)
        if stamp and (
                card.working_on_updated_at is None or stamp > card.working_on_updated_at):
            update["working_on_updated_at"] = stamp

    expertise = sorted(
        (f for f in facts if fact_predicate(f) == "has_expertise_in"),
        key=_confidence,
        reverse=True,
    )
    if expertise:
        update["can_help_with"] = merge_unique(
            [fact_object(f) for f in expertise], card.can_help_with, CAN_HELP_WITH_CAP)

    card = without_old_exploring(card, now)
    return card.model_copy(update=update) if update else card


def without_old_exploring(card: AgentProfileCard, now: datetime | None = None) -> AgentProfileCard:
    """The card without the clips older than EXPLORING_VISIBLE_DAYS: what every public read shows."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=EXPLORING_VISIBLE_DAYS)
    recent = [i for i in card.exploring if _added_after(i.added_at, cutoff)]
    return card if len(recent) == len(card.exploring) else card.model_copy(update={"exploring": recent})
