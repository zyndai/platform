"""URL scraping via Jina Reader (free, JS-capable, LLM-optimised markdown).

Jina Reader (r.jina.ai) fetches any public URL on its own servers and returns
clean markdown. No API key needed for the free tier (~20 req/min), which is
well above our usage. Concurrent scrapes share a semaphore to avoid bursting.

No fallback httpx path — direct httpx to user-supplied URLs is an SSRF vector
(attacker could target 169.254.169.254 or internal services). Jina fetches on
their infrastructure, so there is no SSRF risk on our side.
"""

import asyncio
import re
from urllib.parse import urlparse

import httpx

_JINA_BASE = "https://r.jina.ai/"
_JINA_HEADERS = {
    "Accept": "text/plain",
    "X-Return-Format": "markdown",
    "X-Locale": "en",
}
_MAX_CHARS = 8_000
_JINA_TIMEOUT = 30

# Limit concurrent Jina requests to stay within free-tier rate limits
_semaphore = asyncio.Semaphore(3)

# Known link-in-bio / Linktree-style hosts
_LINKTREE_HOSTS = {
    "linktr.ee", "lnk.bio", "beacons.ai", "bio.link",
    "linktree.com", "campsite.bio", "carrd.co", "solo.to",
}

# Max portfolio links to follow from a Linktree page
_MAX_LINKTREE_LINKS = 5

# Registered domains whose any subdomain should be skipped in link extraction
_SKIP_DOMAINS = _LINKTREE_HOSTS | {
    "r.jina.ai", "fonts.googleapis.com", "cdn.jsdelivr.net",
    "unpkg.com", "www.w3.org", "googleapis.com", "gstatic.com",
    "jsdelivr.net", "cloudflare.com",
}

# File extensions that indicate non-scrapeable resources
_SKIP_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
                    ".css", ".js", ".woff", ".woff2", ".ttf"}


def _is_skip_host(host: str) -> bool:
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in _SKIP_DOMAINS)


def is_linktree(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host in _LINKTREE_HOSTS


async def _jina_fetch(url: str) -> str:
    async with _semaphore:
        # follow_redirects=False: prevent Jina's API from redirecting our client
        # to an attacker-controlled or internal address.
        async with httpx.AsyncClient(timeout=_JINA_TIMEOUT) as client:
            resp = await client.get(
                f"{_JINA_BASE}{url}",
                headers=_JINA_HEADERS,
                follow_redirects=False,
            )
            resp.raise_for_status()
            return resp.text.strip()


def _extract_urls(markdown: str) -> list[str]:
    """Extract unique http(s) URLs from Jina markdown, skipping CDN/meta/image URLs."""
    raw = re.findall(r'https?://[^\s\)\]\"\'<>]+', markdown)
    seen: set[str] = set()
    result: list[str] = []
    for url in raw:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
        if _is_skip_host(host):
            continue
        if any(path.endswith(ext) for ext in _SKIP_EXTENSIONS):
            continue
        base_host = host.removeprefix("www.")
        if base_host in seen:
            continue
        seen.add(base_host)
        result.append(url)
    return result[:_MAX_LINKTREE_LINKS]


async def fetch_linktree_links(url: str) -> list[str]:
    """Fetch a Linktree-style page and return discovered portfolio/website URLs."""
    markdown = await _jina_fetch(url)
    return _extract_urls(markdown)


async def fetch_website(url: str) -> str:
    """Return clean text from a public URL via Jina Reader, capped at 8 000 chars."""
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url!r}")

    text = await _jina_fetch(url)
    return text[:_MAX_CHARS]
