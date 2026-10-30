"""A2 — invite to claim.

A search turns up someone on LinkedIn who has no claimed Card. The searcher invites them:
the person becomes a pre-filled UNCLAIMED Card (name, headline and LinkedIn link, all public
LinkedIn data and nothing else), the searcher gets a link to send them, and the connection
request is delivered when they claim it. Claiming already requires signing in with the same
LinkedIn account (cards.claim_card_by_owner), so the invite cannot be taken by anyone else.

Behind FEATURE_A2_INVITE_TO_CLAIM. All state is in cards.connection_invites; delivery uses the
same code as an ordinary connection request.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException

import config
from models.card import AgentProfileCard
from services import cards as cards_service
from services import network

logger = logging.getLogger(__name__)

MAX_INVITES_PER_DAY = 10
_LINKEDIN_IN = re.compile(r"^/in/([A-Za-z0-9%_\-]{2,100})/?$")


def enabled() -> bool:
    return bool(config.FEATURE_A2_INVITE_TO_CLAIM) and config.SUPABASE_DB_SCHEMA == "cards"


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(404, "Invitations are not enabled")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean_linkedin_url(value: str) -> str:
    """https://www.linkedin.com/in/<slug>, or 422. Only personal profiles qualify."""
    raw = (value or "").strip()
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    match = _LINKEDIN_IN.match(parsed.path or "")
    if parsed.scheme not in ("http", "https") or host not in ("linkedin.com",) and not host.endswith(".linkedin.com") or not match:
        raise HTTPException(422, "Invite needs a LinkedIn profile URL (linkedin.com/in/…)")
    return f"https://www.linkedin.com/in/{match.group(1).lower()}"


def _text(value: str | None, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


def _find_by_linkedin(url: str) -> dict | None:
    """The published Card (claimed or not) that links this LinkedIn profile, if any."""
    wanted = cards_service.linkedin_handle_from_url(url)
    for row in cards_service.list_published_rows(columns="id,card,handle,owner_email"):
        linked = (((row.get("card") or {}).get("identity") or {}).get("links") or {}).get("linkedin")
        if wanted and cards_service.linkedin_handle_from_url(linked) == wanted:
            return row
    return None


def _card_url(handle: str) -> str:
    return config.profile_url(handle)


def _invites():
    return network._sb().table("connection_invites")


def create_invite(user_id: str, *, linkedin_url: str, name: str, headline: str = "", message: str = "") -> dict:
    """Invite the person behind `linkedin_url`. name / headline must come from a trusted source
    (Memory signs them from its own search result): they are published on the new Card."""
    _require_enabled()
    requester = network._card_for_user(user_id)
    url = clean_linkedin_url(linkedin_url)
    name, headline = _text(name, 120), _text(headline, 200)
    if not name:
        raise HTTPException(422, "A name is needed to prepare their Card")

    since = (_now() - timedelta(days=1)).isoformat()
    recent = _invites().select("id", count="exact").eq("inviter_user_id", user_id).gte("created_at", since).execute()
    if (recent.count or 0) >= MAX_INVITES_PER_DAY:
        raise HTTPException(429, f"At most {MAX_INVITES_PER_DAY} invitations a day")

    target = _find_by_linkedin(url)
    if target and cards_service._claimed_from_row(target):
        raise HTTPException(409, {"error": "They already have a Card: connect directly", "handle": target.get("handle")})
    if target is None:
        card = AgentProfileCard(
            id=str(uuid4()), status="published",
            identity={"name": name, "headline": headline, "avatar_url": "", "links": {"linkedin": url}},
        )
        handle = cards_service.insert_card(card, None, None, created_via="invite")
        target = {"id": card.id, "handle": handle}

    existing = (
        _invites().select("*").eq("inviter_user_id", user_id).eq("target_card_id", target["id"])
        .eq("status", "pending").limit(1).execute().data or []
    )
    if existing:
        row, created = existing[0], False
    else:
        row = _invites().insert({
            "inviter_user_id": user_id,
            "inviter_card_id": requester["id"],
            "target_card_id": target["id"],
            "message": _text(message, 500) or None,
        }).execute().data[0]
        created = True
    link = _card_url(target["handle"])
    return {
        "invite": public_invite(row, target["handle"]),
        "created": created,
        "claim_url": link,
        "share_text": f"I'd like to connect with you on Zynd. Your Card is ready to claim: {link}",
    }


def public_invite(row: dict, handle: str | None = None) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "target_handle": handle,
        "created_at": row.get("created_at"),
        "expires_at": row.get("expires_at"),
        "delivered_at": row.get("delivered_at"),
    }


def list_invites(user_id: str) -> dict:
    _require_enabled()
    rows = _invites().select("*").eq("inviter_user_id", user_id).order("created_at", desc=True).limit(50).execute().data or []
    handles = _handles_for([r["target_card_id"] for r in rows])
    return {"invites": [public_invite(r, handles.get(r["target_card_id"])) for r in rows]}


def cancel_invite(user_id: str, invite_id: str) -> dict:
    _require_enabled()
    done = (
        _invites().update({"status": "cancelled"}).eq("id", invite_id)
        .eq("inviter_user_id", user_id).eq("status", "pending").execute().data or []
    )
    if not done:
        raise HTTPException(404, "No pending invitation with that id")
    return {"invite": public_invite(done[0])}


def _handles_for(card_ids: list[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(card_ids))
    if not ids:
        return {}
    rows = network._sb().table("agent_profile_cards").select("id,handle").in_("id", ids).execute().data or []
    return {r["id"]: r["handle"] for r in rows}


def deliver_for_card(card_id: str, recipient_user_id: str) -> int:
    """Turn every pending invitation for this (now claimed) Card into a connection request.

    Idempotent: an invitation is delivered once, and a pair that is already connected (in
    either direction) gets that existing connection instead of a second one. Returns how many
    were delivered. Never raises: a failure here must not break a claim or a connections list.
    """
    if not enabled():
        return 0
    try:
        rows = _invites().select("*").eq("target_card_id", card_id).eq("status", "pending").execute().data or []
        if not rows:
            return 0
        recipient = network._sb().table("agent_profile_cards").select("id,handle,owner_user_id,card") \
            .eq("id", card_id).limit(1).execute().data or []
        if not recipient:
            return 0
        delivered = 0
        for invite in rows:
            if invite["expires_at"] and datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00")) < _now():
                _invites().update({"status": "expired"}).eq("id", invite["id"]).execute()
                continue
            inviter_user = invite["inviter_user_id"]
            if inviter_user == recipient_user_id:
                continue
            inviter_card = network._sb().table("agent_profile_cards").select("id,handle,owner_user_id,card") \
                .eq("id", invite["inviter_card_id"]).limit(1).execute().data or []
            if not inviter_card or inviter_card[0].get("owner_user_id") != inviter_user:
                continue
            connection, _existed = network._create_connection(
                inviter_user, inviter_card[0], recipient_user_id, recipient[0], invite.get("message"))
            _invites().update({
                "status": "delivered", "delivered_at": _now().isoformat(), "connection_id": connection["id"],
            }).eq("id", invite["id"]).execute()
            delivered += 1
        return delivered
    except Exception:  # noqa: BLE001
        logger.exception("invite delivery failed card=%s", card_id)
        return 0


def deliver_for_user(user_id: str) -> int:
    """Deliver invitations waiting for this person's claimed Card (used when they open Connections)."""
    if not enabled():
        return 0
    try:
        card = network._card_for_user(user_id)
    except HTTPException:
        return 0
    return deliver_for_card(card["id"], user_id)
