"""Stale "Working on": whether a card's Working on list has gone unchanged too long to trust.

A Working on list written once and never touched keeps telling visitors and AI agents what the
owner did months ago. agent_profile_cards.working_on_updated_at (cards migration 0033) records
when the list last changed: a database trigger stamps it on every write that changes
card->'working_on', whichever path made it (cards-api, s10_save_section, companion_save_fields),
and mirrors it into the card JSON as `working_on_updated_at`. The owner can also confirm the list
is still true, which resets it without changing the list (confirm_working_on below).

Rules:
  - unknown (NULL, a card from before 0033, or 0033 not applied) is NEVER stale: missing data
    must not dim anybody's card.
  - an empty list has nothing to go stale.
  - the public list merges live `is_working_on` memory facts in first (services/signals.py), and
    those are fresh by definition, so derive_public_signals moves the stamp up to the newest one.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from postgrest.exceptions import APIError

import config
from models.card import AgentProfileCard
from services import card_cache

logger = logging.getLogger(__name__)

# Roughly a quarter: long enough that an active builder's list is never flagged between real
# updates, short enough that a list from last year is. The web mirrors this in lib/stale-signals.ts.
STALE_DAYS = 90

# PostgREST answers PGRST204 when an update names a column its schema cache does not have, and
# Postgres 42703 for an undefined column: both mean migration 0033 is not applied yet.
_MISSING_COLUMN_CODES = {"PGRST204", "42703"}


def enabled() -> bool:
    return config.FEATURE_STALE_SIGNALS


def for_public_read(card: AgentProfileCard) -> AgentProfileCard:
    """The card with its working_on_updated_at dropped while the flag is off. The 0033 trigger
    mirrors the stamp into the card JSON whatever the flag says, and flag off must leave public
    reads exactly as they were. Reads only: writes keep the mirror, which the trigger owns."""
    if enabled() or card.working_on_updated_at is None:
        return card
    return card.model_copy(update={"working_on_updated_at": None})


def working_on_is_stale(card: AgentProfileCard, now: datetime | None = None) -> bool:
    """True only when the card shows Working on items and their known stamp is STALE_DAYS old."""
    if not any(isinstance(item, str) and item.strip() for item in card.working_on):
        return False
    stamp = card.working_on_updated_at
    if stamp is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - stamp >= timedelta(days=STALE_DAYS)


def confirm_working_on(handle: str, email: str, now: datetime | None = None) -> datetime:
    """The owner says their Working on is still true: reset the stamp, leave the list alone.

    Only the column is written; the trigger keeps an explicit value when working_on is unchanged
    and mirrors it into the card JSON, so this cannot race a concurrent card edit.
    """
    from services.cards import _like_literal

    now = now or datetime.now(timezone.utc)
    sb = config.get_supabase()
    rows = (sb.table("agent_profile_cards").select("id,owner_email,status").eq("handle", handle)
            .neq("status", "merged").limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Card not found")
    owner = (rows[0].get("owner_email") or "").strip().lower()
    if not owner or owner != email.strip().lower():
        raise HTTPException(403, "Only the card's owner can confirm this")
    try:
        saved = (sb.table("agent_profile_cards").update({"working_on_updated_at": now.isoformat()})
                 .eq("id", rows[0]["id"]).ilike("owner_email", _like_literal(email))
                 .neq("status", "merged").execute().data)
    except APIError as exc:
        if str(exc.code) in _MISSING_COLUMN_CODES:
            logger.warning("working_on confirm unavailable: cards migration 0033 not applied (%s)", exc.code)
            raise HTTPException(503, "Confirming isn't available yet") from exc
        raise
    card_cache.invalidate()
    if not saved:
        # Ownership or status changed between the read and the write.
        raise HTTPException(409, "Your card changed. Reload and try again.")
    return now
