import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

_HEADERS = {"User-Agent": "ZyndBot/1.0 (+https://zynd.ai/for-ai)"}
_MAX_BYTES = 524_288  # 512 KB cap before decode
_MAX_CHARS = 8_000

# Block RFC-1918 / loopback / link-local (AWS metadata) ranges
_BLOCKED_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_safe_url(url: str) -> bool:
    """Return True only if the URL resolves to a public, non-private IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for _family, _type, _proto, _canon, sockaddr in addrs:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if any(addr in net for net in _BLOCKED_NETS):
            return False
    return True


async def fetch_website(url: str) -> str:
    """Fetch a public URL and return plain text, capped at 8 000 chars.

    Validates each URL in the redirect chain to prevent SSRF.
    Streams the response body to enforce a hard byte cap before decode.
    """
    # Manually follow redirects so we can validate each hop
    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
        current = url
        for _ in range(5):
            if not _is_safe_url(current):
                raise ValueError(f"URL not allowed (private or invalid): {current}")
            resp = await client.get(current, headers=_HEADERS)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    break
                current = location
                continue
            resp.raise_for_status()
            # Stream body to enforce hard byte cap before decode
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(chunk_size=8192):
                total += len(chunk)
                chunks.append(chunk)
                if total >= _MAX_BYTES:
                    break
            html = b"".join(chunks).decode("utf-8", errors="replace")
            break
        else:
            raise ValueError("Too many redirects")

    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&[a-z#0-9]+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()[:_MAX_CHARS]
