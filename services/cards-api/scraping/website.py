"""URL scraping via Jina Reader (free, JS-capable, LLM-optimised markdown).

Jina Reader (r.jina.ai) fetches any public URL on its own servers and returns
clean markdown. No API key needed for the free tier (~20 req/min), which is
well above our usage. Concurrent scrapes share a semaphore to avoid bursting.

No fallback httpx path — direct httpx to user-supplied URLs is an SSRF vector
(attacker could target 169.254.169.254 or internal services). Jina fetches on
their infrastructure, so there is no SSRF risk on our side.
"""

import asyncio

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


async def fetch_website(url: str) -> str:
    """Return clean text from a public URL via Jina Reader, capped at 8 000 chars."""
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url!r}")

    text = await _jina_fetch(url)
    return text[:_MAX_CHARS]
