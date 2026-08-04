"""
LinkedIn endpoints — kicks off background scraping and exposes the
stored result for the frontend.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import config
from api.auth import get_current_user
from services.linkedin_scraper import scrape_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_supabase():
    return config.get_supabase()


async def _safe_scrape(user_id: str, full_name: str, profile_url: str | None = None) -> None:
    try:
        result = await scrape_user(user_id, full_name, profile_url)
        logger.info(f"[linkedin] background scrape done for {user_id}: {result}")
    except Exception as e:
        logger.error(f"[linkedin] background scrape crashed for {user_id}: {e}")


@router.post("/scrape")
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    force: bool = False,
):
    """
    Kick off a LinkedIn scrape for the current user. Returns immediately;
    the scrape runs in the background and persists to linkedin_profiles.
    Safe to call multiple times — the underlying upsert is idempotent.

    If a profile_url was stored from a prior OAuth connect, it is passed
    directly to the scraper, avoiding the fragile search-by-name step.

    `force=True` (the Accounts page's "Refresh now" button) bypasses the
    cached-data short-circuit below. There's no periodic re-scrape job —
    this is the only way data ever gets refreshed after the first scrape.
    """
    metadata = user.get("user_metadata") or {}
    full_name = metadata.get("full_name") or metadata.get("name") or ""

    sb = _get_supabase()
    existing = (
        sb.table("linkedin_profiles")
        .select("scraped_at, profile_url, raw_profile")
        .eq("user_id", user["id"])
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        # A truthy `scraped_at` alone isn't proof of a real scrape — the
        # OIDC-userinfo placeholder written right after OAuth connect used
        # to stamp it too, which made this short-circuit forever and left
        # raw_profile stuck with no headline/experience/etc (see
        # linkedin_callback). Require actual profile content as well, so a
        # user stuck with an old placeholder row can self-heal by hitting
        # connect again instead of being told to disconnect/reconnect.
        raw_profile = row.get("raw_profile") or {}
        has_real_data = any(
            key in raw_profile
            for key in ("headline", "experience", "education", "skills", "summary")
        )
        if not force and row.get("scraped_at") and has_real_data:
            return {"status": "cached", "scraped_at": row["scraped_at"]}
        # If we have a profile_url from OAuth but no scrape data yet, use it.
        if row.get("profile_url"):
            background_tasks.add_task(_safe_scrape, user["id"], full_name, row["profile_url"])
            return {"status": "started", "source": "oauth_profile_url"}

    # No existing row at all — need a name to search by.
    if not full_name:
        return {"status": "skipped", "reason": "no_name_in_metadata"}

    background_tasks.add_task(_safe_scrape, user["id"], full_name)
    return {"status": "started", "source": "search_by_name"}


@router.get("/me")
async def my_linkedin(user: dict = Depends(get_current_user)):
    """Return whatever LinkedIn data we've scraped for this user, if any."""
    sb = _get_supabase()
    result = (
        sb.table("linkedin_profiles")
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    )
    if not result.data:
        return {"present": False}
    row = result.data[0]
    return {"present": True, **row}


@router.delete("/me")
async def disconnect_linkedin(user: dict = Depends(get_current_user)):
    """Wipe the user's LinkedIn scrape. Used by the Settings → Accounts
    'Disconnect' action on the LinkedIn card. Aria stops referencing the
    cached profile/posts; a fresh scrape can be re-triggered any time."""
    sb = _get_supabase()
    sb.table("linkedin_profiles").delete().eq("user_id", user["id"]).execute()
    return {"status": "disconnected"}
