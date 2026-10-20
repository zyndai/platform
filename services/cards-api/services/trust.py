"""A6 — trust and safety for Cards networking.

  - request limits: how many connection requests one person can send a week, and how many
    unanswered requests one person can be sitting on, so nobody can be spammed or spam
  - report a Card (spam, impersonation, harassment): stored for a person to review; nothing
    automatic happens to the reported Card
  - block a Card: the pair can no longer request each other, and the blocked person is hidden
    from the blocker's searches
  - verification badges: which identities of a Card's owner are proven (today only LinkedIn,
    when the owner signed in with the LinkedIn account matching the Card). Stored apart from the
    owner-editable card JSON so an owner cannot award themselves a badge.

Behind FEATURE_NETWORK_CONTROLS (needs packages/db 0025).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

import config
from services import network

MAX_REQUESTS_PER_WEEK = 25
MAX_PENDING_INCOMING = 50
MAX_REPORTS_PER_DAY = 5
REPORT_REASONS = ("spam", "impersonation", "harassment", "inaccurate", "other")


def enabled() -> bool:
    return bool(config.FEATURE_NETWORK_CONTROLS) and config.SUPABASE_DB_SCHEMA == "cards"


def require_enabled() -> None:
    if not enabled():
        raise HTTPException(404, "Network controls are not enabled")


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def check_request_limits(user_id: str, recipient_user_id: str) -> None:
    """Raise 429 / 409 when this request would exceed a limit. No-op when the feature is off."""
    if not enabled():
        return
    sent = (network._sb().table("connections").select("id", count="exact")
            .eq("requester_user_id", user_id).gte("created_at", _ago(days=7)).execute())
    if (sent.count or 0) >= MAX_REQUESTS_PER_WEEK:
        raise HTTPException(429, f"You can send at most {MAX_REQUESTS_PER_WEEK} connection requests a week")
    waiting = (network._sb().table("connections").select("id", count="exact")
               .eq("recipient_user_id", recipient_user_id).eq("status", "pending").execute())
    if (waiting.count or 0) >= MAX_PENDING_INCOMING:
        raise HTTPException(409, "They have a lot of unanswered requests right now; try again later")


def report_card(user_id: str, handle: str, reason: str, details: str = "") -> dict:
    require_enabled()
    if reason not in REPORT_REASONS:
        raise HTTPException(422, "reason must be one of: " + ", ".join(REPORT_REASONS))
    target = _published_card(handle)
    if target.get("owner_user_id") == user_id:
        raise HTTPException(422, "You cannot report your own Card")
    today = (network._sb().table("card_reports").select("id", count="exact")
             .eq("reporter_user_id", user_id).gte("created_at", _ago(days=1)).execute())
    if (today.count or 0) >= MAX_REPORTS_PER_DAY:
        raise HTTPException(429, f"At most {MAX_REPORTS_PER_DAY} reports a day")
    open_ = (network._sb().table("card_reports").select("id").eq("reporter_user_id", user_id)
             .eq("target_card_id", target["id"]).eq("status", "open").limit(1).execute().data or [])
    if open_:
        return {"reported": True, "handle": target["handle"], "already_reported": True}
    network._sb().table("card_reports").insert({
        "reporter_user_id": user_id, "target_card_id": target["id"], "reason": reason,
        "details": " ".join((details or "").split())[:1000] or None,
    }).execute()
    return {"reported": True, "handle": target["handle"], "already_reported": False}


def _published_card(handle: str) -> dict:
    rows = (network._sb().table("agent_profile_cards").select("id,handle,owner_user_id")
            .eq("handle", handle.strip().lstrip("@")).eq("status", "published").limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Card not found")
    return rows[0]


def block_card(user_id: str, handle: str) -> dict:
    """Block the person behind a claimed Card, whether or not you were connected."""
    require_enabled()
    mine = network._card_for_user(user_id)
    target = network._card_for_handle(handle)
    other = target["owner_user_id"]
    if other == user_id:
        raise HTTPException(422, "You cannot block yourself")
    row, _existed = network._create_connection(user_id, mine, other, target, None)
    now = datetime.now(timezone.utc).isoformat()
    network._sb().table("connections").update({"status": "blocked", "decided_at": now, "updated_at": now}) \
        .eq("id", row["id"]).execute()
    from services import match_prefs
    match_prefs.add(user_id, "hide_person", target["handle"])
    return {"blocked": True, "handle": target["handle"]}


def record_verification(card_id: str, provider: str) -> None:
    """Remember that an identity of this Card's owner was proven. Best effort, never raises."""
    if not enabled():
        return
    try:
        network._sb().table("card_verifications").upsert(
            {"card_id": card_id, "provider": provider}, on_conflict="card_id,provider", ignore_duplicates=True).execute()
    except Exception:  # noqa: BLE001 — a badge must never break a claim
        return


def verified_by_card_ids(card_ids: list[str]) -> dict[str, list[str]]:
    ids = [c for c in dict.fromkeys(card_ids) if c]
    if not enabled() or not ids:
        return {}
    try:
        rows = network._sb().table("card_verifications").select("card_id,provider").in_("card_id", ids).execute().data or []
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["card_id"], []).append(r["provider"])
    return {k: sorted(v) for k, v in out.items()}
