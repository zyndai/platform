"""
LinkedIn scraper service — wraps the harvestapi suite on Apify.

Three actors are used in sequence:
  1. harvestapi/linkedin-profile-search-by-name → profile URL
  2. harvestapi/linkedin-profile-scraper        → headline, summary, skills
  3. harvestapi/linkedin-profile-posts          → recent posts

Results land in the public.linkedin_profiles Supabase table. Aria's bio
synthesis (LLM-driven) reads from that table later; this module only
fetches and persists raw data.
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from supabase import create_client

import config

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
SEARCH_BY_NAME_ACTOR = "harvestapi~linkedin-profile-search-by-name"
PROFILE_ACTOR = "harvestapi~linkedin-profile-scraper"
POSTS_ACTOR = "harvestapi~linkedin-profile-posts"

# Per-call timeout for Apify run-sync. Each actor takes ~10-60s in practice;
# 120s gives headroom without leaving requests dangling forever.
_ACTOR_TIMEOUT = 120.0


def _get_supabase():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


async def _run_actor(actor_id: str, payload: dict) -> list:
    """Run an Apify actor synchronously and return its dataset items."""
    if not config.APIFY_API_TOKEN:
        raise RuntimeError("APIFY_API_TOKEN is not configured")

    url = (
        f"{APIFY_BASE}/acts/{actor_id}/run-sync-get-dataset-items"
        f"?token={config.APIFY_API_TOKEN}"
    )
    async with httpx.AsyncClient(timeout=_ACTOR_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json() or []


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


async def find_profile_url(full_name: str) -> str | None:
    """Search LinkedIn by name; return the top-match profile URL, or None."""
    first, last = _split_name(full_name)
    if not first:
        return None

    items = await _run_actor(
        SEARCH_BY_NAME_ACTOR,
        {
            "profileScraperMode": "Short",
            "firstName": first,
            "lastName": last,
            "strictSearch": True,
            "maxItems": 5,
        },
    )
    if not items:
        return None

    # Result records expose either `linkedinUrl`, `profileUrl`, or `url`
    # depending on actor version. Pick the first non-empty one.
    top = items[0]
    return (
        top.get("linkedinUrl")
        or top.get("profileUrl")
        or top.get("url")
    )


async def scrape_profile(profile_url: str) -> dict:
    """Fetch the full profile blob for a URL."""
    items = await _run_actor(
        PROFILE_ACTOR,
        {
            "profileScraperMode": "Profile details",
            "urls": [profile_url],
        },
    )
    return items[0] if items else {}


async def scrape_recent_posts(profile_url: str, max_posts: int = 10) -> list[dict]:
    """Fetch recent posts authored by the profile."""
    return await _run_actor(
        POSTS_ACTOR,
        {
            "targetUrls": [profile_url],
            "maxPosts": max_posts,
            "postedLimit": "month",
            "includeReposts": False,
        },
    )


async def scrape_user(user_id: str, full_name: str) -> dict:
    """
    End-to-end scrape: find the profile URL, fetch profile + posts in
    parallel, persist to public.linkedin_profiles. Idempotent — calling
    twice for the same user upserts.
    """
    if not full_name:
        return {"status": "skipped", "reason": "no_name"}

    try:
        profile_url = await find_profile_url(full_name)
    except Exception as e:
        logger.warning(f"[linkedin] search-by-name failed for {user_id}: {e}")
        return {"status": "error", "stage": "search", "detail": str(e)}

    if not profile_url:
        logger.info(f"[linkedin] no profile match for {user_id} ({full_name!r})")
        return {"status": "no_match"}

    profile_task = scrape_profile(profile_url)
    posts_task = scrape_recent_posts(profile_url)
    profile, posts = await asyncio.gather(
        profile_task, posts_task, return_exceptions=True
    )

    if isinstance(profile, Exception):
        logger.warning(f"[linkedin] profile scrape failed for {user_id}: {profile}")
        profile = {}
    if isinstance(posts, Exception):
        logger.warning(f"[linkedin] posts scrape failed for {user_id}: {posts}")
        posts = []

    sb = _get_supabase()
    sb.table("linkedin_profiles").upsert(
        {
            "user_id": user_id,
            "profile_url": profile_url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_profile": profile,
            "raw_posts": posts,
        },
        on_conflict="user_id",
    ).execute()

    logger.info(
        f"[linkedin] stored profile + {len(posts)} posts for {user_id} "
        f"({profile_url})"
    )
    return {"status": "ok", "profile_url": profile_url, "posts_count": len(posts)}
