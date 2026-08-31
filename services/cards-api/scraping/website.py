"""URL scraping via Jina Reader (free, JS-capable, LLM-optimised markdown).

Jina Reader (r.jina.ai) fetches any public URL on its own servers and returns
clean markdown. No API key needed for the free tier (~20 req/min), which is
well above our usage. Concurrent scrapes share a semaphore to avoid bursting.

Fallback to raw httpx if Jina returns too little content (< 200 chars) —
handles cases where Jina blocks or rate-limits the target site.
"""

import asyncio
import re

import httpx

_JINA_BASE = "https://r.jina.ai/"
_JINA_HEADERS = {
    "Accept": "text/plain",
    "X-Return-Format": "markdown",
    "X-Locale": "en",
}
_FALLBACK_HEADERS = {"User-Agent": "ZyndBot/1.0 (+https://zynd.ai/for-ai)"}
_MAX_CHARS = 8_000
_JINA_TIMEOUT = 30
_FALLBACK_TIMEOUT = 15
_FALLBACK_MAX_BYTES = 524_288  # 512 KB

# Limit concurrent Jina requests to stay within free-tier rate limits
_semaphore = asyncio.Semaphore(3)


async def _jina_fetch(url: str) -> str:
    async with _semaphore:
        async with httpx.AsyncClient(timeout=_JINA_TIMEOUT) as client:
            resp = await client.get(
                f"{_JINA_BASE}{url}",
                headers=_JINA_HEADERS,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text.strip()


async def _fallback_fetch(url: str) -> str:
    """Raw httpx scrape — static sites only, strips HTML tags."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=_FALLBACK_TIMEOUT
    ) as client:
        async with client.stream("GET", url, headers=_FALLBACK_HEADERS) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(chunk_size=8192):
                total += len(chunk)
                chunks.append(chunk)
                if total >= _FALLBACK_MAX_BYTES:
                    break
            html = b"".join(chunks).decode("utf-8", errors="replace")

    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&[a-z#0-9]+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()


async def fetch_website(url: str) -> str:
    """Return clean text from a public URL, capped at 8 000 chars.

    Tries Jina Reader first (free, JS-capable). Falls back to raw httpx
    when Jina returns too little content or errors.
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url!r}")

    try:
        text = await _jina_fetch(url)
        if len(text) >= 200:
            return text[:_MAX_CHARS]
    except Exception:
        pass

    # Fallback: static HTML scrape
    text = await _fallback_fetch(url)
    return text[:_MAX_CHARS]
