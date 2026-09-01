"""X / Twitter profile + recent tweets via Apify (data-slayer, no auth).

Profile: data-slayer~twitter-user  — $1.50/1K profiles
Tweets:  data-slayer~twitter-user-tweets — $1.50/1K tweets, capped at 10

Both fetches run concurrently. Falls back to Jina Reader on Apify failure.
"""

import asyncio
from urllib.parse import urlparse

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR_PROFILE = "data-slayer~twitter-user"
_ACTOR_TWEETS  = "data-slayer~twitter-user-tweets"
_MAX_TWEETS = 10
_MAX_CHARS = 8_000


def _handle_from_url(url: str) -> str | None:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else None


async def fetch_x_profile(url: str) -> str:
    """Scrape public X/Twitter profile + recent tweets. Apify if key set, else Jina."""
    if config.APIFY_API_KEY:
        try:
            return await _apify_fetch(url)
        except Exception:
            pass
    from scraping.website import _jina_fetch
    try:
        return (await _jina_fetch(url))[:_MAX_CHARS]
    except Exception:
        return ""


async def _apify_fetch(url: str) -> str:
    handle = _handle_from_url(url)
    if not handle:
        raise ValueError(f"Cannot extract handle from URL: {url!r}")

    profile_text, tweets_text = await asyncio.gather(
        _fetch_profile(handle),
        _fetch_tweets(handle),
        return_exceptions=True,
    )

    parts: list[str] = []
    if isinstance(profile_text, str) and profile_text:
        parts.append(profile_text)
    if isinstance(tweets_text, str) and tweets_text:
        parts.append(tweets_text)
    return "\n\n".join(parts)[:_MAX_CHARS]


async def _fetch_profile(handle: str) -> str:
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_PROFILE}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 60, "memory": 256},
            json={"username": handle},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return ""

    user = items[0]
    parts: list[str] = []
    if user.get("name"):
        parts.append(f"Name: {user['name']}")
    if user.get("profile") or handle:
        parts.append(f"Handle: @{user.get('profile') or handle}")
    if user.get("desc"):
        parts.append(f"Bio: {user['desc']}")
    if user.get("location"):
        parts.append(f"Location: {user['location']}")
    if user.get("sub_count") is not None:
        parts.append(f"Followers: {user['sub_count']}")
    if user.get("blue_verified"):
        parts.append("Verified: yes")
    return "\n".join(parts)


async def _fetch_tweets(handle: str) -> str:
    # memory=256 + timeout=40s keeps the run to the first page (~20 tweets)
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_TWEETS}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 40, "memory": 256},
            json={"userId": handle},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return ""

    lines = ["Recent posts:"]
    for tweet in items[:_MAX_TWEETS]:
        text = tweet.get("text") or ""
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines) if len(lines) > 1 else ""
