import hmac

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel

import config
from services.digest import clear_suggested_posts, run_digest

router = APIRouter()


class OwnerStatusRequest(BaseModel):
    email: str


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


@router.post("/owner-notifications")
async def owner_notifications(authorization: str | None = Header(default=None), dry_run: bool = Query(default=False)):
    _require_cron(authorization)
    from services.owner_notifications import run_notifications
    return await run_notifications(dry_run=dry_run)


def _require_cron(authorization: str | None) -> None:
    secret = (config.CRON_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not set")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/morning-digest")
def morning_digest(
    authorization: str | None = Header(default=None),
    dry_run: bool = Query(default=False),
    handle: str | None = Query(default=None),
):
    _require_cron(authorization)
    return run_digest(dry_run=dry_run, handle=handle)


@router.post("/clear-suggested-posts")
def clear_suggested_posts_route(
    authorization: str | None = Header(default=None),
    handle: str | None = Query(default=None),
):
    _require_cron(authorization)
    return clear_suggested_posts(handle=handle)


@router.post("/purge-card-events")
def purge_card_events(authorization: str | None = Header(default=None)):
    """S04: drop card_events older than 180 days. Flag off → 204."""
    _require_cron(authorization)
    from services import events as events_service

    if not events_service.events_enabled():
        return Response(status_code=204)
    deleted = events_service.purge_older_than_days(180)
    return {"deleted": deleted}
