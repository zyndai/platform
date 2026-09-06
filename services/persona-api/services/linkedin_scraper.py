"""
LinkedIn scraper service — wraps the harvestapi suite on Apify.

Two actors are used:
  1. harvestapi/linkedin-profile-scraper        → headline, summary, skills
  2. harvestapi/linkedin-profile-posts          → latest 5 posts

Results land in the public.linkedin_profiles Supabase table. The scrape
is strictly opt-in: the profile URL must be supplied by the user (name
guessing was removed entirely). After a successful profile persist, the
curated facts are also synced into the memory layer, deduped — only new
info is declared (see sync_profile_to_memory).
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

import config

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
PROFILE_ACTOR = "harvestapi~linkedin-profile-scraper"
POSTS_ACTOR = "harvestapi~linkedin-profile-posts"
# General keyword/role/location people search — powers open-ended
# discovery ("find AI founders on LinkedIn") via the search_linkedin_people
# MCP tool. Distinct from the two scrape actors above and never runs
# during a profile scrape.
PEOPLE_SEARCH_ACTOR = "harvestapi~linkedin-profile-search"

# Per-call timeout for Apify run-sync. Each actor takes ~10-60s in practice;
# 120s gives headroom without leaving requests dangling forever.
_ACTOR_TIMEOUT = 120.0


def _get_supabase():
    return config.get_supabase()


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
        if resp.status_code >= 400:
            # httpx's raise_for_status() only gives the status line — the
            # actual reason (e.g. Apify's actors renaming/removing an input
            # enum value out from under us, like profileScraperMode did) is
            # in the response body. Losing that meant every past failure
            # here needed a manual reproduction to diagnose. Log it once,
            # then still raise so callers' existing except-and-record-failure
            # behavior is unchanged.
            logger.error(f"[linkedin] actor {actor_id} returned {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        return resp.json() or []


async def scrape_profile(profile_url: str) -> dict:
    """Fetch the full profile blob for a URL."""
    items = await _run_actor(
        PROFILE_ACTOR,
        {
            # harvestapi renamed its accepted profileScraperMode values to
            # be pricing-qualified ("Profile details" alone is no longer
            # valid) — every scrape was failing with a 400 until this was
            # updated to match. No email search needed here, so the cheaper
            # tier is the right one.
            "profileScraperMode": "Profile details no email ($4 per 1k)",
            "urls": [profile_url],
        },
    )
    return items[0] if items else {}


async def scrape_profile_only(user_id: str, profile_url: str) -> dict:
    """
    Fetch just the profile actor (headline/summary/skills/experience/etc,
    no posts) and persist it.

    Used by onboarding's autofill step, which needs this data back fast —
    running it alongside the posts actor (as scrape_user does) makes the
    user wait on whichever of the two is slower, for data the onboarding
    form doesn't even use yet. Posts are backfilled separately by
    scrape_posts_only once the user reaches a later onboarding step that
    actually needs them (matches/brief).
    """
    logger.info(f"[linkedin] starting profile-only scrape for {user_id} ({profile_url})")
    try:
        profile = await scrape_profile(profile_url)
    except Exception as e:
        logger.warning(f"[linkedin] profile-only scrape failed for {user_id}: {e}")
        return {"status": "error", "detail": str(e)}

    sb = _get_supabase()

    # Same "don't overwrite good data with an empty scrape" guard as scrape_user.
    profile_empty = not profile or not any(
        key in (profile or {})
        for key in ("headline", "experience", "education", "skills", "summary")
    )
    if profile_empty:
        existing = (
            sb.table("linkedin_profiles")
            .select("raw_profile")
            .eq("user_id", user_id)
            .execute()
        )
        if existing.data and existing.data[0].get("raw_profile"):
            existing_profile = existing.data[0]["raw_profile"]
            if existing_profile and any(
                key in (existing_profile or {})
                for key in ("headline", "experience", "education", "skills", "summary")
            ):
                logger.warning(
                    f"[linkedin] skipping profile-only upsert for {user_id} — new scrape "
                    f"returned empty, and existing data is still good"
                )
                return {"status": "skipped", "reason": "empty_scrape_preserved_existing"}

    sb.table("linkedin_profiles").upsert(
        {
            "user_id": user_id,
            "profile_url": profile_url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_profile": profile,
        },
        on_conflict="user_id",
    ).execute()

    logger.info(f"[linkedin] stored profile-only for {user_id} ({profile_url})")
    await _safe_memory_sync(user_id, profile)
    return {"status": "ok", "profile_url": profile_url}


async def scrape_posts_only(user_id: str, profile_url: str) -> dict:
    """
    Backfill raw_posts for a user whose profile was already stored via
    scrape_profile_only. Runs independently so nothing in onboarding waits
    on it. A partial upsert (only user_id/profile_url/raw_posts in the
    payload) — PostgREST's upsert only touches the columns present in the
    payload, so raw_profile/scraped_at from the earlier profile-only
    upsert are left untouched.
    """
    logger.info(f"[linkedin] starting posts-only scrape for {user_id} ({profile_url})")
    try:
        posts = await scrape_recent_posts(profile_url)
    except Exception as e:
        logger.warning(f"[linkedin] posts-only scrape failed for {user_id}: {e}")
        return {"status": "error", "detail": str(e)}

    sb = _get_supabase()
    sb.table("linkedin_profiles").upsert(
        {"user_id": user_id, "profile_url": profile_url, "raw_posts": posts},
        on_conflict="user_id",
    ).execute()

    logger.info(f"[linkedin] stored {len(posts)} posts for {user_id} ({profile_url})")
    return {"status": "ok", "posts_count": len(posts)}


async def search_people(
    query: str = "",
    locations: list[str] | None = None,
    max_items: int = 10,
) -> list[dict]:
    """
    Keyword/role/location people search across LinkedIn (not a specific
    person lookup — a profile scrape always takes an explicit URL).
    Backs the `search_linkedin_people` MCP tool.

    Field names on the returned dicts (firstName/lastName, headline,
    location.linkedinText, linkedinUrl, currentPosition[].companyName) are
    now confirmed against the actor's real input/output schema (fetched
    directly from Apify's API, not the marketing page) — see
    verification notes in the PR/commit history for the raw schema dump.

    `takePages` has no default on the actor's side (confirmed via its
    input schema) — omitting it makes the actor scrape zero search-result
    pages and return an empty list regardless of query, independent of
    `maxItems`. This was the actual bug behind "LinkedIn search always
    comes back empty": every call was missing this field. Each page holds
    up to 25 profiles, so we request enough pages to cover `max_items`.
    """
    max_items = max(1, min(int(max_items or 10), 20))
    payload: dict = {
        "profileScraperMode": "Short",
        "maxItems": max_items,
        "takePages": max(1, -(-max_items // 25)),  # ceil(max_items / 25)
    }
    if query:
        payload["searchQuery"] = query
    if locations:
        payload["locations"] = locations
    return await _run_actor(PEOPLE_SEARCH_ACTOR, payload)


async def scrape_recent_posts(profile_url: str, max_posts: int = 5) -> list[dict]:
    """Fetch the latest posts authored by the profile (5 by default)."""
    return await _run_actor(
        POSTS_ACTOR,
        {
            "targetUrls": [profile_url],
            "maxPosts": max_posts,
            "postedLimit": "month",
            "includeReposts": False,
        },
    )


async def scrape_user(user_id: str, profile_url: str) -> dict:
    """
    End-to-end scrape of a known profile URL: fetch profile + posts in
    parallel, persist to linkedin_profiles, and sync curated facts to the
    memory layer (deduped). Idempotent — calling twice upserts.

    The URL is mandatory. Name-based guessing was removed entirely, so a
    user who never supplies their profile URL never gets scraped.
    """
    if not profile_url:
        return {"status": "skipped", "reason": "no_profile_url"}

    # Log the attempt before awaiting anything below. Past incidents had
    # this coroutine start and then never produce another log line at all
    # (no success, no failure, no exception) when run as a FastAPI
    # BackgroundTask on a busy event loop — with no "started" marker there
    # was no way to tell "never ran" apart from "ran and silently hung"
    # without attaching a live debugger.
    logger.info(f"[linkedin] starting profile+posts scrape for {user_id} ({profile_url})")

    profile_task = scrape_profile(profile_url)
    posts_task = scrape_recent_posts(profile_url)
    profile, posts = await asyncio.gather(
        profile_task, posts_task, return_exceptions=True
    )

    if isinstance(profile, Exception):
        # An exception here means the actor call itself failed (network
        # error, Apify billing/rate limit, etc.) — distinct from "the actor
        # ran fine and found nothing" (a genuinely empty/restricted
        # profile). Converting this to an empty dict and writing it below
        # used to stamp scraped_at on a row with no real data, making a
        # failed scrape indistinguishable from a completed-but-empty one —
        # nothing would ever retry it since scraped_at looked legitimate.
        # Abort without touching the DB so the next call retries cleanly.
        logger.warning(f"[linkedin] profile scrape failed for {user_id}: {profile}")
        return {"status": "error", "stage": "profile", "detail": str(profile)}
    if isinstance(posts, Exception):
        logger.warning(f"[linkedin] posts scrape failed for {user_id}: {posts}")
        posts = []

    sb = _get_supabase()

    # Don't overwrite existing good data with an empty scrape.
    # An empty profile dict means the Apify actor returned nothing — usually
    # because of rate limits, wrong profile URL, or a restricted profile.
    profile_empty = not profile or not any(
        key in (profile or {})
        for key in ("headline", "experience", "education", "skills", "summary")
    )
    if profile_empty:
        existing = (
            sb.table("linkedin_profiles")
            .select("raw_profile")
            .eq("user_id", user_id)
            .execute()
        )
        if existing.data and existing.data[0].get("raw_profile"):
            existing_profile = existing.data[0]["raw_profile"]
            if existing_profile and any(
                key in (existing_profile or {})
                for key in ("headline", "experience", "education", "skills", "summary")
            ):
                logger.warning(
                    f"[linkedin] skipping upsert for {user_id} — new scrape returned empty, "
                    f"and existing data is still good (profile_url={profile_url})"
                )
                return {"status": "skipped", "reason": "empty_scrape_preserved_existing"}

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
    await _safe_memory_sync(user_id, profile)
    return {"status": "ok", "profile_url": profile_url, "posts_count": len(posts)}


# ── Memory sync ──────────────────────────────────────────────────────

MAX_SKILL_FACTS = 8


def _extract_facts(profile: dict) -> list[tuple[str, str]]:
    """Curated (predicate, value) facts from a raw_profile blob.

    Deliberately small and high-signal — the same shape the persona
    surfaces elsewhere (works_at / lives_in / has_skill), not a full
    dump of the profile.
    """
    facts: list[tuple[str, str]] = []

    experience = profile.get("experience") or []
    if experience:
        first = experience[0] if isinstance(experience[0], dict) else {}
        title = str(first.get("title") or "").strip()
        company = str(first.get("companyName") or first.get("company") or "").strip()
        if title or company:
            value = f"{title} at {company}" if title and company else (title or company)
            facts.append(("works_at", value))

    location = str(profile.get("location") or "").strip()
    if location:
        facts.append(("lives_in", location))

    for skill in (profile.get("skills") or [])[:MAX_SKILL_FACTS]:
        name = skill.get("name") if isinstance(skill, dict) else skill
        name = str(name or "").strip()
        if name:
            facts.append(("has_skill", name))

    return facts


async def _compose_profile_summary(user_id: str, profile: dict) -> str:
    """LLM-composed first-person memory note about the profile.

    Falls back to a plain template when the LLM is unreachable — the
    summary is a bonus, never a dependency of the scrape.
    """
    headline = str(profile.get("headline") or "").strip()
    facts = _extract_facts(profile)
    works_at = next((v for p, v in facts if p == "works_at"), "")
    skills = [v for p, v in facts if p == "has_skill"]

    if works_at or skills:
        prompt = (
            "Write a private memory note about a person's LinkedIn profile, "
            "in their own first-person voice. Use only the facts given. "
            "3-5 short declarative sentences. Lead with their current role, "
            "then main skills. No fluff, no markdown, no bullet lists.\n\n"
        )
        if headline:
            prompt += f"Headline: {headline}\n"
        prompt += f"Current role: {works_at}\nMain skills: {', '.join(skills)}"
        try:
            from agent.orchestrator import _get_provider

            provider = _get_provider()
            text, _ = await asyncio.to_thread(
                provider.chat_with_tools,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Write the note."},
                ],
                [],
            )
            if text and text.strip():
                return text.strip()
        except Exception as exc:
            logger.warning("[linkedin] %s: summary LLM call failed: %s", user_id, exc)

    parts = []
    if headline:
        parts.append(f'My LinkedIn headline is "{headline}".')
    if works_at:
        parts.append(f"I work as {works_at}.")
    if skills:
        parts.append("My main skills include: " + ", ".join(skills) + ".")
    return " ".join(parts)


async def sync_profile_to_memory(user_id: str, profile: dict) -> dict:
    """Write the IMPORTANT LinkedIn facts to the memory layer, deduped.

    Curated, not everything:
      • works_at   — the current position ("<title> at <company>")
      • lives_in   — the profile location
      • has_skill  — the first MAX_SKILL_FACTS skills
    Plus one LLM-composed first-person summary ingested with
    source_system="linkedin" for async extraction — only when at least
    one new fact was declared, so an unchanged re-scrape writes nothing.

    Diffed against the user's current assertion graph (list_assertions)
    so only new (predicate, object) pairs are declared. Fire-and-forget:
    memory-layer problems are logged and never block the scrape.
    """
    from agent.memory_client import (
        declare_fact,
        ingest_turns,
        is_enabled,
        list_assertions,
    )

    if not is_enabled():
        return {"facts_declared": 0}

    facts = _extract_facts(profile)
    if not facts:
        return {"facts_declared": 0}

    try:
        existing = await list_assertions(user_id)
        seen = {(a.predicate, (a.object or "").strip().lower()) for a in existing}
        new_facts = [
            (p, v) for p, v in facts if (p, v.strip().lower()) not in seen
        ]
    except Exception as exc:
        logger.warning("[linkedin] memory graph read failed for %s: %s", user_id, exc)
        return {"facts_declared": 0}

    declared = 0
    for predicate, value in new_facts:
        try:
            if await declare_fact(user_id, predicate, value, source_system="linkedin"):
                declared += 1
        except Exception as exc:
            logger.warning(
                "[linkedin] declare_fact(%s, %r) failed for %s: %s",
                predicate, value, user_id, exc,
            )

    if declared:
        summary = await _compose_profile_summary(user_id, profile)
        if summary:
            try:
                await ingest_turns(
                    user_id,
                    turns=[{"role": "user", "content": summary}],
                    source_system="linkedin",
                )
            except Exception as exc:
                logger.warning("[linkedin] summary ingest failed for %s: %s", user_id, exc)

    logger.info(
        "[linkedin] memory sync for %s: %d new facts declared (of %d extracted)",
        user_id, declared, len(facts),
    )
    return {"facts_declared": declared}


async def _safe_memory_sync(user_id: str, profile: dict) -> None:
    """Wrapper — a memory-sync failure must never fail the scrape that
    triggered it. sync_profile_to_memory already catches most errors;
    this is the last line of defense."""
    try:
        await sync_profile_to_memory(user_id, profile)
    except Exception as exc:
        logger.warning(f"[linkedin] memory sync failed for {user_id}: {exc}")
