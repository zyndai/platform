"""LinkedIn profile scraping via Apify linkedin-profile-scraper.

LinkedIn requires authenticated cookies to scrape reliably. The Apify actor
`apify/linkedin-profile-scraper` handles this but needs a `cookie` param
(LinkedIn session cookie from a logged-in account).

Without cookies, falls back to Jina Reader for whatever public metadata
LinkedIn exposes (name, title, sometimes headline) — limited but better than
nothing.

To enable full scraping: set LINKEDIN_COOKIE in .env.prod to a valid
LinkedIn `li_at` session cookie value.
"""

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR = "apify~linkedin-profile-scraper"
_MAX_CHARS = 8_000


async def fetch_linkedin_profile(url: str) -> str:
    """Scrape a LinkedIn profile. Needs LINKEDIN_COOKIE for full data."""
    cookie = getattr(config, "LINKEDIN_COOKIE", "")
    if config.APIFY_API_KEY and cookie:
        try:
            return await _apify_fetch(url, cookie)
        except Exception:
            pass
    # Best-effort: Jina Reader returns OG metadata and partial public content
    from scraping.website import _jina_fetch
    try:
        text = await _jina_fetch(url)
        if len(text) >= 100:
            return text[:_MAX_CHARS]
    except Exception:
        pass
    return ""


async def _apify_fetch(url: str, cookie: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={
                "profileUrls": [url],
                "cookie": [{"name": "li_at", "value": cookie}],
            },
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return ""

    profile = items[0]
    parts: list[str] = []

    if profile.get("fullName"):
        parts.append(f"Name: {profile['fullName']}")
    if profile.get("headline"):
        parts.append(f"Headline: {profile['headline']}")
    if profile.get("summary"):
        parts.append(f"About: {profile['summary']}")
    if profile.get("location"):
        parts.append(f"Location: {profile['location']}")

    skills = [s.get("name") for s in (profile.get("skills") or []) if s.get("name")]
    if skills:
        parts.append(f"Skills: {', '.join(skills)}")

    experience = profile.get("positions") or []
    for exp in experience[:3]:
        title = exp.get("title") or ""
        company = exp.get("companyName") or ""
        if title or company:
            parts.append(f"Experience: {title} at {company}".strip(" at"))

    return "\n".join(parts)[:_MAX_CHARS]
