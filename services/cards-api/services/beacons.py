"""Owner-authored broadcasts in the existing card JSON, with exact expiry."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from models.card import AgentProfileCard, Beacon
import config
from services import card_cache


def active_beacon(card: AgentProfileCard, now: datetime | None = None) -> Beacon | None:
    now = now or datetime.now(timezone.utc)
    beacon = card.beacon
    return beacon if beacon and beacon.created_at <= now < beacon.expires_at else None


def save_beacon(handle: str, email: str, text: str | None) -> dict | None:
    from services.cards import _like_literal
    now = datetime.now(timezone.utc)
    beacon = Beacon(text=text.strip(), created_at=now, expires_at=now + timedelta(days=7)) if text else None
    value = beacon.model_dump(mode="json") if beacon else None
    sb = config.get_supabase()
    rows = (sb.table("agent_profile_cards").select("id,card,updated_at").eq("handle", handle)
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
    return value


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
