"""X / Twitter profile scraping via Apify twitter-scraper.

Fetches a public X profile + up to 10 recent posts for skill/interest signal.
Falls back to Jina Reader if Apify is not configured or errors.

Cost control:
- memory=512MB (minimum for Twitter's JS-heavy pages)
- actor timeout=60s, max 10 posts
- Single profile URL only — no follower/following crawl
"""

from urllib.parse import urlparse

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR = "apify~twitter-scraper"
_MAX_CHARS = 8_000


def _handle_from_url(url: str) -> str | None:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else None


async def fetch_x_profile(url: str) -> str:
    """Scrape a public X/Twitter profile. Uses Apify if key set, else Jina."""
    if config.APIFY_API_KEY:
        try:
            return await _apify_fetch(url)
        except Exception:
            pass
    # Jina fallback — works for some public profiles
    from scraping.website import _jina_fetch
    try:
        return (await _jina_fetch(url))[:_MAX_CHARS]
    except Exception:
        return ""


async def _apify_fetch(url: str) -> str:
    handle = _handle_from_url(url)
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 60, "memory": 512},
            json={
                "startUrls": [{"url": url}],
                "maxTweets": 10,
                "addUserInfo": True,
            },
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return ""

    parts: list[str] = []

    # User info from first item's author field
    author = items[0].get("author") or {}
    if author:
        if author.get("name"):
            parts.append(f"Name: {author['name']}")
        if author.get("userName") or handle:
            parts.append(f"Handle: @{author.get('userName') or handle}")
        if author.get("description"):
            parts.append(f"Bio: {author['description']}")
        if author.get("location"):
            parts.append(f"Location: {author['location']}")
        urls = author.get("entities", {}).get("url", {}).get("urls") or []
        if urls:
            parts.append(f"Website: {urls[0].get('expanded_url', '')}")

    # Recent posts for skill/interest signal
    tweets = [
        item.get("text") or item.get("fullText") or ""
        for item in items[:10]
        if item.get("text") or item.get("fullText")
    ]
    if tweets:
        parts.append("\nRecent posts:\n" + "\n".join(tweets))

    return "\n".join(parts)[:_MAX_CHARS]
