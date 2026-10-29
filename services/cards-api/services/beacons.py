"""Owner-authored broadcasts in the existing card JSON, with exact expiry."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from models.card import AgentProfileCard, Beacon
import config
from services import card_cache

logger = logging.getLogger(__name__)


def active_beacon(card: AgentProfileCard, now: datetime | None = None) -> Beacon | None:
    now = now or datetime.now(timezone.utc)
    beacon = card.beacon
    return beacon if beacon and beacon.created_at <= now < beacon.expires_at else None


def save_beacon(handle: str, email: str, text: str | None) -> dict | None:
    from services.cards import _like_literal
    now = datetime.now(timezone.utc)
    # The ask id is made here so the card JSON can name it without waiting for the asks table.
    beacon = (Beacon(id=str(uuid4()), text=text.strip(), created_at=now, expires_at=now + timedelta(days=7))
              if text else None)
    value = beacon.model_dump(mode="json") if beacon else None
    sb = config.get_supabase()
    rows = (sb.table("agent_profile_cards").select("id,card,updated_at,handle,owner_user_id").eq("handle", handle)
            .ilike("owner_email", _like_literal(email)).neq("status", "merged").limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Card not found for this owner")
    row = rows[0]
    data = {**row["card"], "beacon": value, "updated_at": now.isoformat()}
    # Preserve concurrent profile edits instead of replacing a newer card snapshot.
    saved = (sb.table("agent_profile_cards").update({"card": data, "updated_at": now.isoformat()})
             .eq("id", row["id"]).eq("updated_at", row["updated_at"])
             .ilike("owner_email", _like_literal(email)).neq("status", "merged").execute().data)
    card_cache.invalidate()
    if not saved:
        raise HTTPException(409, "Your card changed. Reload before publishing this beacon.")
    try:
        _track_ask(row, beacon, now)
    except Exception:  # noqa: BLE001 — publishing must never fail because of asks
        logger.warning("beacons: asks bookkeeping failed")
    return value


def _track_ask(row: dict, beacon: Beacon | None, now: datetime) -> None:
    """Asks bookkeeping after the card write succeeded. It can never fail the publish or the dismiss:
    asks.py swallows its own errors and does nothing at all until migration 0033 is applied."""
    from services import asks

    if beacon is None:
        asks.record_dismiss(row["id"], now)
    elif asks.record_publish(row, beacon.id, beacon.text, beacon.created_at, beacon.expires_at):
        asks.schedule_routing(beacon.id, {**row, "card": row["card"]}, beacon.text)


def candidate_rows() -> list[dict]:
    """Page only rows carrying beacon JSON; expired values are filtered by the caller."""
    sb = config.get_supabase()
    rows, start = [], 0
    while True:
        page = (sb.table("agent_profile_cards").select("id,handle,card,owner_email,embedding")
                .eq("status", "published").not_.is_("card->>beacon", "null")
                .order("id").range(start, start + 999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000
