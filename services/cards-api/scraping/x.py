"""X / Twitter profile scraping via Apify data-slayer~twitter-user.

$1.50 / 1,000 profiles. No auth required.
Input: { "username": "handle" } — handle without @ extracted from URL.
Falls back to Jina Reader if Apify not configured or errors.
"""

from urllib.parse import urlparse

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR = "data-slayer~twitter-user"
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
    from scraping.website import _jina_fetch
    try:
        return (await _jina_fetch(url))[:_MAX_CHARS]
    except Exception:
        return ""


async def _apify_fetch(url: str) -> str:
    handle = _handle_from_url(url)
    if not handle:
        raise ValueError(f"Cannot extract handle from URL: {url!r}")

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR}/run-sync-get-dataset-items",
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

    return "\n".join(parts)[:_MAX_CHARS]
