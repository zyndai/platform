"""
Twitter (X) endpoints — kicks off background scraping and exposes the
stored result for the frontend (Settings → Accounts "X (Twitter)" card).
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import config
from api.auth import get_current_user
from services.twitter_scraper import normalize_handle, scrape_user

logger = logging.getLogger(__name__)
router = APIRouter()

TABLE = "twitter_profiles"


def _get_supabase():
    return config.get_supabase()


async def _safe_scrape(user_id: str, handle: str) -> None:
    try:
        result = await scrape_user(user_id, handle)
        logger.info(f"[twitter] background scrape done for {user_id}: {result}")
    except Exception as e:
        logger.error(f"[twitter] background scrape crashed for {user_id}: {e}")


async def _stored_handle(user_id: str) -> str | None:
    """The handle from a previous scrape/save, if any."""
    sb = _get_supabase()
    rows = await sb.table(TABLE).select("handle").eq("user_id", user_id).execute()
    if rows.data:
        return rows.data[0].get("handle") or None
    return None


@router.post("/scrape")
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    handle: str | None = None,
):
    """
    Kick off a Twitter scrape for the current user. Returns immediately;
    the scrape runs in the background and persists to twitter_profiles.
    Safe to call multiple times — the underlying upsert is idempotent.

    A handle is mandatory and strictly opt-in: it's accepted directly
    (saved from the Accounts card's input) or taken from a stored prior
    save; with neither present this returns `no_handle` and nothing runs.
    """
    if handle:
        normalized = normalize_handle(handle)
        if not normalized:
            raise HTTPException(
                status_code=400,
                detail="That doesn't look like an X/Twitter handle — expected something like @yourhandle or https://x.com/yourhandle.",
            )
        handle = normalized
        sb = _get_supabase()
        sb.table(TABLE).upsert(
            {"user_id": user["id"], "handle": handle},
            on_conflict="user_id",
        ).execute()
        background_tasks.add_task(_safe_scrape, user["id"], handle)
        return {"status": "started", "source": "user_provided_handle"}

    stored = await _stored_handle(user["id"])
    if stored:
        background_tasks.add_task(_safe_scrape, user["id"], stored)
        return {"status": "started", "source": "stored_handle"}

    return {"status": "skipped", "reason": "no_handle"}


@router.get("/me")
async def my_twitter(user: dict = Depends(get_current_user)):
    """Return whatever Twitter data we've scraped for this user, if any."""
    sb = _get_supabase()
    result = (
        sb.table(TABLE)
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    )
    if not result.data:
        return {"present": False}
    row = result.data[0]
    raw_tweets = row.get("raw_tweets") or []
    return {"present": True, **row, "tweets_count": len(raw_tweets)}


@router.delete("/me")
async def disconnect_twitter(user: dict = Depends(get_current_user)):
    """Wipe the user's Twitter scrape. Used by the Settings → Accounts
    'Disconnect' action on the X (Twitter) card. Aria stops referencing
    the cached tweets; a fresh scrape can be re-triggered any time.
    Declared memory facts are left in place (same as LinkedIn) — the user
    can forget them individually on the Memory page."""
    sb = _get_supabase()
    sb.table(TABLE).delete().eq("user_id", user["id"]).execute()
    return {"status": "disconnected"}
