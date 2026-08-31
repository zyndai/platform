import re

import httpx

_HEADERS = {"User-Agent": "ZyndBot/1.0 (+https://zynd.ai/for-ai)"}
_MAX_CHARS = 8_000


async def fetch_website(url: str) -> str:
    """Fetch a public URL and return plain text, capped at 8 000 chars."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        html = resp.text

    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&[a-z#0-9]+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()[:_MAX_CHARS]
