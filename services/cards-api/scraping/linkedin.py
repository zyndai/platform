"""LinkedIn profile scraping via Apify atomus~linkedin-profile-scraper.

$6 / 1,000 profiles. No cookies or account required.
Input: { "profileUrls": ["https://www.linkedin.com/in/handle/"] }
Output: [{ status: "success"|"not_found"|"error", profile: { ... } }]

Falls back to Jina Reader on Apify failure (returns limited public metadata).
"""

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR = "atomus~linkedin-profile-scraper"
_MAX_CHARS = 8_000


async def fetch_linkedin_profile(url: str) -> str:
    """Scrape a LinkedIn profile. No cookies needed."""
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
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR}/run-sync-get-dataset-items",
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

    return "\n".join(parts)[:_MAX_CHARS]
