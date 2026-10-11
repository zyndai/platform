import hmac

from fastapi import APIRouter, Header, HTTPException, Query, Response

import config
from services.digest import clear_suggested_posts, run_digest

router = APIRouter()


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
