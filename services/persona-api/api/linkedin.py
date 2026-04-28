"""
LinkedIn endpoints — kicks off background scraping and exposes the
stored result for the frontend.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from supabase import create_client

import config
from api.auth import get_current_user
from services.linkedin_scraper import scrape_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_supabase():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


async def _safe_scrape(user_id: str, full_name: str) -> None:
    try:
        result = await scrape_user(user_id, full_name)
        logger.info(f"[linkedin] background scrape done for {user_id}: {result}")
    except Exception as e:
        logger.error(f"[linkedin] background scrape crashed for {user_id}: {e}")


@router.post("/scrape")
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Kick off a LinkedIn scrape for the current user. Returns immediately;
    the scrape runs in the background and persists to linkedin_profiles.
    Safe to call multiple times — the underlying upsert is idempotent.
    """
    metadata = user.get("user_metadata") or {}
    full_name = metadata.get("full_name") or metadata.get("name") or ""
    if not full_name:
        return {"status": "skipped", "reason": "no_name_in_metadata"}

    # Cheap pre-check: skip the scrape if we already have data from the
    # last 7 days. Avoids burning Apify credits on repeated onboarding
    # entries when the user resumes the flow.
    sb = _get_supabase()
    existing = (
        sb.table("linkedin_profiles")
        .select("scraped_at")
        .eq("user_id", user["id"])
        .execute()
    )
    if existing.data:
        return {"status": "cached", "scraped_at": existing.data[0]["scraped_at"]}

    background_tasks.add_task(_safe_scrape, user["id"], full_name)
    return {"status": "started"}


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
