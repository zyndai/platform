"""LinkedIn profile + recent posts via Apify actors (no cookies).

Profile: bebity~linkedin-profile-scraper (primary)  — flat response, widely reliable
         atomus~linkedin-profile-scraper (fallback)  — nested under 'profile' key
Posts:   atomus~linkedin-posts-scraper-pro           — $2/1K posts, capped at 15

Both profile and posts fetches run concurrently. Falls back to Jina Reader on Apify failure.
Returns tuple[str, dict | None] — (profile_text, linkedin_stats).
"""

import asyncio

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR_PROFILE_PRIMARY  = "bebity~linkedin-profile-scraper"
_ACTOR_PROFILE_FALLBACK = "atomus~linkedin-profile-scraper"
_ACTOR_POSTS = "atomus~linkedin-posts-scraper-pro"
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


def _skill_name(s) -> str:
    if isinstance(s, str):
        return s
    if isinstance(s, dict):
        return s.get("name") or s.get("skill") or ""
    return ""


def _parse_bebity_profile(record: dict) -> tuple[str, dict | None]:
    """Parse flat bebity~linkedin-profile-scraper response."""
    parts: list[str] = []

    full_name = (
        record.get("fullName")
        or f"{record.get('firstName', '')} {record.get('lastName', '')}".strip()
    )
    if full_name:
        parts.append(f"Name: {full_name}")
    if record.get("headline"):
        parts.append(f"Headline: {record['headline']}")

    about = record.get("summary") or record.get("about") or record.get("description") or ""
    if about:
        parts.append(f"About: {about}")

    loc = record.get("location") or ""
    if isinstance(loc, dict):
        loc = loc.get("default") or loc.get("name") or ""
    if loc:
        parts.append(f"Location: {loc}")

    pic = (
        record.get("profilePicture")
        or record.get("pictureUrl")
        or record.get("profilePicUrl")
        or record.get("imgUrl")
        or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    skills = record.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    experience = record.get("experience") or record.get("positions") or []
    for exp in experience[:3]:
        if not isinstance(exp, dict):
            continue
        title = exp.get("title") or exp.get("position") or ""
        company = exp.get("companyName") or exp.get("company") or ""
        if isinstance(company, dict):
            company = company.get("name") or ""
        if title or company:
            entry = f"{title} at {company}".strip(" at")
            parts.append(f"Experience: {entry}")

    connections_raw = (
        record.get("connections")
        or record.get("connectionsCount")
        or record.get("connectionCount")
        or record.get("connections_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None:
        linkedin_stats = {"connections": _compact_connections(connections_raw), "posts": 0}

    return "\n".join(parts), linkedin_stats


def _parse_atomus_profile(record: dict) -> tuple[str, dict | None]:
    """Parse atomus~linkedin-profile-scraper response — nested under 'profile' key.
    Does NOT check 'status' field — extracts whatever data is present."""
    profile = record.get("profile") or {}

    # If no nested profile object, the actor may have returned a flat structure
    if not profile and (record.get("headline") or record.get("fullName")):
        return _parse_bebity_profile(record)

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
    if isinstance(loc, dict) and loc.get("default"):
        parts.append(f"Location: {loc['default']}")
    elif isinstance(loc, str) and loc:
        parts.append(f"Location: {loc}")

    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")

    pic = (
        record.get("picture_url") or record.get("pictureUrl")
        or profile.get("picture_url") or profile.get("pictureUrl") or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    bg = (
        profile.get("background_url") or profile.get("backgroundUrl")
        or record.get("background_url") or ""
    )
    if bg and bg.startswith("http"):
        parts.append(f"Avatar BG URL: {bg}")

    skills = profile.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    for group in (profile.get("position_groups") or [])[:3]:
        company = (group.get("company") or {}).get("name") or ""
        for pos in (group.get("profile_positions") or [])[:1]:
            title = pos.get("title") or ""
            if title or company:
                parts.append(f"Experience: {title} at {company}".strip(" at"))

    connections_raw = (
        profile.get("connections_count") or profile.get("connectionsCount")
        or record.get("connections_count")
        or profile.get("followersCount") or profile.get("followers_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None:
        linkedin_stats = {"connections": _compact_connections(connections_raw), "posts": 0}

    return "\n".join(parts), linkedin_stats


async def _run_actor(actor: str, payload: dict, timeout_secs: int = 90) -> list:
    async with httpx.AsyncClient(timeout=timeout_secs + 30) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": timeout_secs, "memory": 256},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _fetch_profile(url: str) -> tuple[str, dict | None]:
    # Primary: bebity actor
    try:
        items = await _run_actor(_ACTOR_PROFILE_PRIMARY, {"profileUrls": [url]})
        if items and isinstance(items, list):
            text, stats = _parse_bebity_profile(items[0])
            if text:
                return text, stats
    except Exception:
        pass

    # Fallback: atomus actor
    items = await _run_actor(_ACTOR_PROFILE_FALLBACK, {"profileUrls": [url]})
    if not items:
        return "", None
    return _parse_atomus_profile(items[0])


async def _fetch_posts(url: str) -> tuple[str, int]:
    try:
        items = await _run_actor(
            _ACTOR_POSTS,
            {"profiles": [url], "maxPosts": _MAX_POSTS, "sortBy": "date", "includeText": True},
        )
    except Exception:
        return "", 0

    if not items:
        return "", 0

    lines = ["Recent LinkedIn posts:"]
    for post in items[:_MAX_POSTS]:
        content = post.get("content") or post.get("text") or post.get("postText") or ""
        if content:
            lines.append(f"- {content[:600]}")
    text = "\n".join(lines) if len(lines) > 1 else ""
    return text, len(items)


async def _no_posts() -> tuple[str, int]:
    # Posts scraping disabled — atomus posts actor returns feed posts (others' content), not profile's own posts.
    return "", 0


async def _apify_fetch(url: str) -> tuple[str, dict | None]:
    profile_result, posts_result = await asyncio.gather(
        _fetch_profile(url),
        _no_posts(),
        return_exceptions=True,
    )

    parts: list[str] = []
    linkedin_stats: dict | None = None
    posts_count = 0

    if isinstance(profile_result, tuple):
        profile_text, linkedin_stats = profile_result
        if profile_text:
            parts.append(profile_text)

    if isinstance(posts_result, tuple):
        posts_text, posts_count = posts_result
        if posts_text:
            parts.append(posts_text)

    if linkedin_stats is not None and posts_count:
        linkedin_stats["posts"] = posts_count
    elif linkedin_stats is None and posts_count:
        linkedin_stats = {"connections": "500+", "posts": posts_count}

    return "\n\n".join(parts)[:_MAX_CHARS], linkedin_stats


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
