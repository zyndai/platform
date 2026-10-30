import asyncio
import hmac
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

import config
from services.digest import clear_suggested_posts, run_digest

router = APIRouter()


class OwnerStatusRequest(BaseModel):
    email: str


class CardsForUsersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: list[UUID]


class OwnerIntrosRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zynd_uid: UUID
    issuer: str


@router.post("/owner-intros")
async def service_owner_intros(body: OwnerIntrosRequest, authorization: str | None = Header(default=None)):
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401,"Unauthorized")
    from services import intros
    intros.enabled()
    if body.issuer != config.AAFO_ISSUER:
        raise HTTPException(403,"Shared identity issuer does not match")
    await intros.memory_identity(str(body.zynd_uid))
    result = await intros.persona("/users/" + str(body.zynd_uid))
    intros.require_scope(result["intros"],str(body.zynd_uid))
    await intros.sync(result["intros"])
    return {"intros": [intros.public_record(row) for row in result["intros"]]}


@router.post("/cards-for-users")
async def service_cards_for_users(body: CardsForUsersRequest, authorization: str | None = Header(default=None)):
    """Memory's people search resolves Zynd users to their Cards so one person is one result
    and can be connected to by handle. Public identity only."""
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401, "Unauthorized")
    if len(body.user_ids) > 50:
        raise HTTPException(422, "At most 50 user ids per call")
    from services import cards as cards_service
    cards = await asyncio.to_thread(cards_service.cards_by_owner_user_ids, [str(u) for u in body.user_ids])
    return {"cards": cards}


@router.post("/owner-status")
async def service_owner_status(body: OwnerStatusRequest, authorization: str | None = Header(default=None)):
    # Only memory can vouch for the owner behind an authenticated MCP call.
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ")
    if not secret or not hmac.compare_digest(supplied, secret):
        raise HTTPException(401, "Unauthorized")
    from services import owner_home
    if not owner_home.enabled():
        raise HTTPException(404, "Owner home is not enabled")
    if not body.email.strip():
        raise HTTPException(422, "Email is required")
    return await owner_home.status(body.email.strip().lower(), persist=False)


@router.post("/refresh-card-memory")
async def refresh_card_memory(body: OwnerStatusRequest, authorization: str | None = Header(default=None)):
    # Only memory can vouch for a memory-side mutation (MCP forget/revoke/approve
    # via the agent path) that needs the card snapshot refreshed. See
    # services/memory/app/services/card_sync.py for the caller.
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401, "Unauthorized")
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(422, "Email is required")
    from services.zynd_memory import refresh_owner_snapshot

    snapshot = await asyncio.to_thread(refresh_owner_snapshot, email)
    return {"zynd_memory": snapshot}


@router.post("/owner-notifications")
async def owner_notifications(authorization: str | None = Header(default=None), dry_run: bool = Query(default=False)):
    _require_cron(authorization)
    from services.owner_notifications import run_notifications
    return await run_notifications(dry_run=dry_run)


@router.post("/owner-notifications/test")
async def test_owner_notification(
    authorization: str | None = Header(default=None),
    kind: Literal["weekly", "reminder"] = Query(default="weekly"),
    email: str | None = Query(default=None),
):
    """Explicit repeatable send to one owner, or all owners when email is omitted."""
    _require_cron(authorization)
    from services.owner_notifications import send_test_notification, send_all_test_notifications
    if email is not None:
        return await send_test_notification(email=email, kind=kind)
    return await send_all_test_notifications(kind=kind)


@router.post("/weekly-agent-digest")
async def weekly_agent_digest(
    authorization: str | None = Header(default=None),
    dry_run: bool = Query(default=False),
    email: str | None = Query(default=None),
):
    """Weekly receipts only; shares preference checks and the existing weekly delivery key."""
    _require_cron(authorization)
    from services.owner_notifications import run_notifications
    return await run_notifications(dry_run=dry_run, weekly_only=True, email=email)


@router.post("/weekly-agent-digest/test")
async def test_weekly_agent_digest(
    email: str = Query(...), authorization: str | None = Header(default=None),
):
    """Explicit single-recipient resend; does not claim a weekly delivery."""
    _require_cron(authorization)
    from services.owner_notifications import send_test_notification
    return await send_test_notification(email=email, kind="weekly")


@router.post("/profile-feedback/test")
async def test_profile_feedback(
    email: str | None = Query(default=None), authorization: str | None = Header(default=None),
):
    """Repeatable resend to one owner or all owners; never claims the one-time invitation."""
    _require_cron(authorization)
    from services.owner_notifications import send_test_notification, send_all_test_notifications
    if email is not None:
        return await send_test_notification(email=email, kind="feedback")
    return await send_all_test_notifications(kind="feedback")


@router.post("/profile-feedback")
async def profile_feedback(
    authorization: str | None = Header(default=None),
    email: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
):
    """One lifetime invitation per eligible owner; email optionally narrows the recipient."""
    _require_cron(authorization)
    from services.profile_feedback import run_feedback
    return await run_feedback(email=email, dry_run=dry_run)


def _require_cron(authorization: str | None) -> None:
    secret = (config.CRON_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not set")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/recaps/generate")
async def generate_recaps(authorization: str | None = Header(default=None), dry_run: bool = Query(default=False)):
    _require_cron(authorization)
    from services.recaps import run_scheduled
    result = await run_scheduled(dry_run=dry_run)
    if result["failed"]:
        raise HTTPException(503, detail=result)
    return result


@router.post("/morning-digest")
def morning_digest(
    authorization: str | None = Header(default=None),
    dry_run: bool = Query(default=False),
    handle: str | None = Query(default=None),
    ignore_schedule: bool = Query(default=False),
):
    """Sends to owners whose local time is in their 07:00 window; the workflow calls this
    every 30 minutes. `ignore_schedule` sends to everyone regardless of local time."""
    _require_cron(authorization)
    return run_digest(dry_run=dry_run, handle=handle, ignore_schedule=ignore_schedule)


@router.post("/clear-suggested-posts")
def clear_suggested_posts_route(
    authorization: str | None = Header(default=None),
    handle: str | None = Query(default=None),
):
    _require_cron(authorization)
    return clear_suggested_posts(handle=handle)


@router.post("/saved-searches/run")
async def run_saved_searches(authorization: str | None = Header(default=None)):
    """A3: re-run every active saved search and nudge owners about new strong matches. A no-op
    (enabled: false) unless FEATURE_NETWORK_CONTROLS is on."""
    _require_cron(authorization)
    from services import saved_searches
    return await asyncio.to_thread(saved_searches.run_all)


@router.post("/suggestions/refresh")
async def refresh_suggestions(
    authorization: str | None = Header(default=None),
    handle: str | None = Query(default=None),
):
    """Nightly: store each claimed card's top people to meet (cards.card_suggestions), so the
    digest and owner home read them instead of searching. `handle` refreshes one card."""
    _require_cron(authorization)
    from services import suggestions
    return await asyncio.to_thread(suggestions.refresh_all, handle)


@router.post("/purge-card-events")
def purge_card_events(authorization: str | None = Header(default=None)):
    """S04: drop card_events older than 180 days. Flag off → 204."""
    _require_cron(authorization)
    from services import events as events_service

    if not events_service.events_enabled():
        return Response(status_code=204)
    deleted = events_service.purge_older_than_days(180)
    return {"deleted": deleted}
