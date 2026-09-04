"""LinkedIn profile + recent posts via Apify atomus actors (no cookies).

Profile: atomus~linkedin-profile-scraper  — $6/1K profiles
Posts:   atomus~linkedin-posts-scraper-pro — $2/1K posts, capped at 7

Both fetches run concurrently. Falls back to Jina Reader on Apify failure.
Returns tuple[str, dict | None] — (profile_text, linkedin_stats).
"""

import asyncio

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR_PROFILE = "atomus~linkedin-profile-scraper"
_ACTOR_POSTS   = "atomus~linkedin-posts-scraper-pro"
_MAX_POSTS = 15
_MAX_CHARS = 12_000


def _compact_connections(n: int | str | None) -> str:
    if n is None:
        return "500+"
    try:
        v = int(str(n).replace(",", "").replace("+", "").strip())
        if v >= 500:
            return "500+"
        return str(v)
    except (ValueError, TypeError):
        return str(n)


async def fetch_linkedin_profile(url: str) -> tuple[str, dict | None]:
    """Scrape LinkedIn profile + recent posts. Returns (text, linkedin_stats)."""
    if config.APIFY_API_KEY:
        try:
            return await _apify_fetch(url)
        except Exception:
            pass
    from scraping.website import _jina_fetch
    try:
        text = await _jina_fetch(url)
        if len(text) >= 100:
            return text[:_MAX_CHARS], None
    except Exception:
        pass
    return "", None


async def _apify_fetch(url: str) -> tuple[str, dict | None]:
    profile_result, posts_result = await asyncio.gather(
        _fetch_profile(url),
        _fetch_posts(url),
        return_exceptions=True,
    )

    parts: list[str] = []
    linkedin_stats: dict | None = None
    posts_count = 0

    if isinstance(profile_result, tuple):
        profile_text, linkedin_stats = profile_result
        if profile_text:
            parts.append(profile_text)
    elif isinstance(profile_result, str) and profile_result:
        parts.append(profile_result)

    if isinstance(posts_result, tuple):
        posts_text, posts_count = posts_result
        if posts_text:
            parts.append(posts_text)
    elif isinstance(posts_result, str) and posts_result:
        parts.append(posts_result)

    # Enrich linkedin_stats with actual posts count from Apify data
    if linkedin_stats is not None and posts_count:
        linkedin_stats["posts"] = posts_count
    elif linkedin_stats is None and posts_count:
        linkedin_stats = {"connections": "500+", "posts": posts_count}

    return "\n\n".join(parts)[:_MAX_CHARS], linkedin_stats


async def _fetch_profile(url: str) -> tuple[str, dict | None]:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_PROFILE}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={"profileUrls": [url]},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return "", None

    record = items[0]
    if record.get("status") != "success":
        return "", None

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

    pic = (
        record.get("picture_url")
        or record.get("pictureUrl")
        or profile.get("picture_url")
        or profile.get("pictureUrl")
        or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    bg = (
        profile.get("background_url")
        or profile.get("backgroundUrl")
        or record.get("background_url")
        or ""
    )
    if bg and bg.startswith("http"):
        parts.append(f"Avatar BG URL: {bg}")

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

    # Extract structured stats
    connections_raw = (
        profile.get("connections_count")
        or profile.get("connectionsCount")
        or record.get("connections_count")
        or profile.get("followersCount")
        or profile.get("followers_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None:
        linkedin_stats = {
            "connections": _compact_connections(connections_raw),
            "posts": 0,
        }

    return "\n".join(parts), linkedin_stats


async def _fetch_posts(url: str) -> tuple[str, int]:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_POSTS}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={"profiles": [url], "maxPosts": _MAX_POSTS, "sortBy": "date", "includeText": True},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return "", 0

    lines = ["Recent LinkedIn posts:"]
    for post in items[:_MAX_POSTS]:
        content = post.get("content") or ""
        if content:
            lines.append(f"- {content[:600]}")
    text = "\n".join(lines) if len(lines) > 1 else ""
    return text, len(items)
