"""LinkedIn profile + recent posts via Apify atomus actors (no cookies).

Profile: atomus~linkedin-profile-scraper  — $6/1K profiles
Posts:   atomus~linkedin-posts-scraper-pro — $2/1K posts, capped at 7

Both fetches run concurrently. Falls back to Jina Reader on Apify failure.
"""

import asyncio

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR_PROFILE = "atomus~linkedin-profile-scraper"
_ACTOR_POSTS   = "atomus~linkedin-posts-scraper-pro"
_MAX_POSTS = 7
_MAX_CHARS = 8_000


async def fetch_linkedin_profile(url: str) -> str:
    """Scrape LinkedIn profile + recent posts. Apify if key set, else Jina."""
    if config.APIFY_API_KEY:
        try:
            return await _apify_fetch(url)
        except Exception:
            pass
    from scraping.website import _jina_fetch
    try:
        text = await _jina_fetch(url)
        if len(text) >= 100:
            return text[:_MAX_CHARS]
    except Exception:
        pass
    return ""


async def _apify_fetch(url: str) -> str:
    profile_text, posts_text = await asyncio.gather(
        _fetch_profile(url),
        _fetch_posts(url),
        return_exceptions=True,
    )

    parts: list[str] = []
    if isinstance(profile_text, str) and profile_text:
        parts.append(profile_text)
    if isinstance(posts_text, str) and posts_text:
        parts.append(posts_text)
    return "\n\n".join(parts)[:_MAX_CHARS]


async def _fetch_profile(url: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_PROFILE}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={"profileUrls": [url]},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return ""

    record = items[0]
    if record.get("status") != "success":
        return ""

    profile = record.get("profile") or {}
    parts: list[str] = []

    if profile.get("full_name"):
        parts.append(f"Name: {profile['full_name']}")
    if profile.get("title"):
        parts.append(f"Title: {profile['title']}")
    if profile.get("headline"):
        parts.append(f"Headline: {profile['headline']}")
    if profile.get("summary"):
        parts.append(f"About: {profile['summary']}")

    loc = profile.get("location") or {}
    if loc.get("default"):
        parts.append(f"Location: {loc['default']}")

    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")

    skills = profile.get("skills") or []
    if skills:
        parts.append(f"Skills: {', '.join(skills[:30])}")

    position_groups = profile.get("position_groups") or []
    for group in position_groups[:3]:
        company = (group.get("company") or {}).get("name") or ""
        for pos in (group.get("profile_positions") or [])[:1]:
            title = pos.get("title") or ""
            if title or company:
                parts.append(f"Experience: {title} at {company}".strip(" at"))

    return "\n".join(parts)


async def _fetch_posts(url: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_POSTS}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={"profiles": [url], "maxPosts": _MAX_POSTS, "sortBy": "date"},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return ""

    lines = ["Recent LinkedIn posts:"]
    for post in items[:_MAX_POSTS]:
        content = post.get("content") or ""
        if content:
            lines.append(f"- {content[:400]}")
    return "\n".join(lines) if len(lines) > 1 else ""
