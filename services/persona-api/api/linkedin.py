"""
LinkedIn endpoints — kicks off background scraping and exposes the
stored result for the frontend.
"""

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import config
from api.auth import get_current_user
from services.linkedin_scraper import scrape_user, scrape_profile_only, scrape_posts_only

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_linkedin_url(raw: str) -> str | None:
    """Parse a pasted LinkedIn profile URL into a clean canonical form
    (https://www.linkedin.com/in/<slug>), or return None if it doesn't
    look like one.

    LinkedIn's own /in/me redirect (and most copy-pasted profile links)
    land with tracking query params attached (?trk=..., ?originalSubdomain=...),
    which a regex anchored on `$` right after the slug rejects outright —
    that's what was actually happening when a real, valid profile link
    came back "doesn't look like a LinkedIn profile URL". Parsing the URL
    properly and only checking scheme/host/path means the query string
    and any fragment are simply dropped, not treated as invalid.
    """
    try:
        parsed = urlparse(raw.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2 or parts[0].lower() != "in" or not parts[1]:
        return None
    return f"https://www.linkedin.com/in/{parts[1]}"


def _get_supabase():
    return config.get_supabase()


async def _safe_scrape(user_id: str, profile_url: str) -> None:
    try:
        result = await scrape_user(user_id, profile_url)
        logger.info(f"[linkedin] background scrape done for {user_id}: {result}")
    except Exception as e:
        logger.error(f"[linkedin] background scrape crashed for {user_id}: {e}")


async def _safe_scrape_profile_only(user_id: str, profile_url: str) -> None:
    try:
        result = await scrape_profile_only(user_id, profile_url)
        logger.info(f"[linkedin] background profile-only scrape done for {user_id}: {result}")
    except Exception as e:
        logger.error(f"[linkedin] background profile-only scrape crashed for {user_id}: {e}")


async def _safe_scrape_posts_only(user_id: str, profile_url: str) -> None:
    try:
        result = await scrape_posts_only(user_id, profile_url)
        logger.info(f"[linkedin] background posts-only scrape done for {user_id}: {result}")
    except Exception as e:
        logger.error(f"[linkedin] background posts-only scrape crashed for {user_id}: {e}")


@router.post("/scrape")
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    force: bool = False,
    profile_url: str | None = None,
    fast: bool = False,
):
    """
    Kick off a LinkedIn scrape for the current user. Returns immediately;
    the scrape runs in the background and persists to linkedin_profiles.
    Safe to call multiple times — the underlying upsert is idempotent.

    A profile URL is mandatory: name-based guessing was removed entirely,
    so scraping is strictly opt-in. `profile_url` is accepted directly
    (from the user pasting it) or taken from a stored prior connect; with
    neither present this returns `no_profile_url` and nothing runs.

    `force=True` (the Accounts page's "Refresh now" button) bypasses the
    cached-data short-circuit below. There's no periodic re-scrape job —
    this is the only way data ever gets refreshed after the first scrape.

    `fast=True` (onboarding's LinkedIn step) scrapes just the profile
    actor, skipping posts — the profile+posts actors run in parallel in
    the normal path, so the wait is bounded by whichever is slower, for
    data (headline/summary/skills) the onboarding form doesn't need posts
    for. Posts are backfilled the next time this is called without `fast`
    (see the has_posts branch below), once a later onboarding step
    (matches/brief) actually needs them.
    """
    sb = _get_supabase()

    if profile_url:
        normalized = _normalize_linkedin_url(profile_url)
        if not normalized:
            raise HTTPException(
                status_code=400,
                detail="That doesn't look like a LinkedIn profile URL — expected something like https://www.linkedin.com/in/your-name.",
            )
        profile_url = normalized
        sb.table("linkedin_profiles").upsert(
            {"user_id": user["id"], "profile_url": profile_url},
            on_conflict="user_id",
        ).execute()
        if fast:
            background_tasks.add_task(_safe_scrape_profile_only, user["id"], profile_url)
            return {"status": "started", "source": "user_provided_url_fast"}
        background_tasks.add_task(_safe_scrape, user["id"], profile_url)
        return {"status": "started", "source": "user_provided_url"}

    existing = (
        sb.table("linkedin_profiles")
        .select("scraped_at, profile_url, raw_profile, raw_posts")
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
        has_posts = bool(row.get("raw_posts"))
        if not force and row.get("scraped_at") and has_real_data and has_posts:
            return {"status": "cached", "scraped_at": row["scraped_at"]}
        # Profile came in via the fast onboarding path but posts never got
        # backfilled — fetch just those instead of redoing the profile scrape.
        if not force and has_real_data and not has_posts and row.get("profile_url"):
            background_tasks.add_task(_safe_scrape_posts_only, user["id"], row["profile_url"])
            return {"status": "started", "source": "posts_backfill"}
        # If we have a profile_url from a prior paste/connect but no scrape
        # data yet, use it.
        if row.get("profile_url"):
            background_tasks.add_task(_safe_scrape, user["id"], row["profile_url"])
            return {"status": "started", "source": "oauth_profile_url"}

    # No stored row and no profile URL supplied — with name guessing
    # removed, scraping is strictly opt-in: the user pastes their URL on
    # onboarding or the Accounts page, and nothing runs until they do.
    return {"status": "skipped", "reason": "no_profile_url"}


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


@router.delete("/data")
async def delete_linkedin_data(user: dict = Depends(get_current_user)):
    """Delete the user's stored LinkedIn data while keeping their Zynd
    account and persona. Removes the scraped profile (linkedin_profiles) and
    the LinkedIn OAuth tokens (api_tokens). This is the granular "delete my
    LinkedIn data" compliance action — distinct from a full disconnect,
    though the underlying DB writes are the same."""
    from services.token_store import delete_tokens

    sb = _get_supabase()
    sb.table("linkedin_profiles").delete().eq("user_id", user["id"]).execute()
    delete_tokens(user_id=user["id"], provider="linkedin")
    return {"status": "deleted"}
