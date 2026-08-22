"""
Signup-time user metadata capture — non-intrusive, server-side source of truth.

On a user's first authenticated request the frontend fires
``POST /api/auth/signup-meta`` with a handful of client-only facts
(language, timezone, screen size, platform, touch support, referrer).
The backend adds what the browser can't see on its own:

- the client IP (X-Forwarded-For behind Caddy, falling back to the socket peer)
- the raw + parsed User-Agent (browser, OS, device type)
- a best-effort IP geolocation (country/region/city/timezone/org) via free,
  keyless lookup APIs — coarse, never asked of the user, and skipped for
  private/localhost addresses.

Everything is merged into ``auth.users.user_metadata.signup_meta`` so no new
table or migration is needed, matching how the onboarding state machine
stores its flags. The capture is idempotent: if ``signup_meta`` already
exists, the request is a no-op and the stored record is returned.

Only the backend's service-role client ever writes this metadata.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

GEO_TIMEOUT_SECONDS = 2.0


# ── User-Agent parsing (hand-rolled; UA strings are too messy for one regex) ──

_BROWSER_PATTERNS: list[tuple[str, str]] = [
    ("Edge", r"Edg(?:e|A|iOS)?/(\d+(?:\.\d+)*)"),
    ("Opera", r"OPR/(\d+(?:\.\d+)*)"),
    ("Samsung Internet", r"SamsungBrowser/(\d+(?:\.\d+)*)"),
    ("Chrome", r"(?:Chrome|CriOS)/(\d+(?:\.\d+)*)"),
    ("Firefox", r"(?:Firefox|FxiOS)/(\d+(?:\.\d+)*)"),
    ("Safari", r"Version/(\d+(?:\.\d+)*).*Safari"),
    ("Safari", r"Safari/(\d+(?:\.\d+)*)"),
]

_WINDOWS_VERSIONS = {
    "10.0": "10/11",
    "6.3": "8.1",
    "6.2": "8",
    "6.1": "7",
    "6.0": "Vista",
    "5.1": "XP",
}


def parse_user_agent(ua: Optional[str]) -> dict:
    """Parse browser / OS / device type out of a User-Agent string.

    Defensive by design: every field defaults to None, malformed input
    degrades to ``{"raw": ..., "browser": None, ...}``, and the raw string
    is truncated so a hostile header can't bloat the stored record.
    """
    ua = (ua or "").strip()[:600]
    parsed: dict[str, Any] = {
        "raw": ua or None,
        "browser": None,
        "browser_version": None,
        "os": None,
        "os_version": None,
        "device_type": None,
    }
    if not ua:
        return parsed

    for name, pattern in _BROWSER_PATTERNS:
        match = re.search(pattern, ua)
        if match:
            parsed["browser"] = name
            parsed["browser_version"] = match.group(1)
            break

    os_name: Optional[str] = None
    os_version: Optional[str] = None
    if "Windows Phone" in ua:
        os_name = "Windows Phone"
        match = re.search(r"Windows Phone (?:OS )?([\d.]+)", ua)
        if match:
            os_version = match.group(1)
    else:
        match = re.search(r"Windows NT (\d+\.\d+)", ua)
        if match:
            os_name = "Windows"
            os_version = _WINDOWS_VERSIONS.get(match.group(1), match.group(1))
        else:
            match = re.search(r"Mac OS X (\d+[._]\d+(?:[._]\d+)?)", ua)
            if match:
                os_name = "macOS"
                os_version = match.group(1).replace("_", ".")
            elif "CrOS" in ua:
                os_name = "ChromeOS"
            else:
                match = re.search(r"(?:iPhone OS|CPU OS|CPU iPhone OS|iOS)[ /](\d+[._]\d+(?:[._]\d+)?)", ua)
                if match:
                    os_name = "iOS"
                    os_version = match.group(1).replace("_", ".")
                else:
                    match = re.search(r"Android (\d+(?:\.\d+)*)", ua)
                    if match:
                        os_name = "Android"
                        os_version = match.group(1)
                    elif "Linux" in ua:
                        os_name = "Linux"
                    elif "iPadOS" in ua:
                        os_name = "iPadOS"
    parsed["os"] = os_name
    parsed["os_version"] = os_version

    if re.search(r"iPad|Tablet|Silk|Kindle|PlayBook", ua) or (
        "Android" in ua and "Mobile" not in ua
    ):
        device_type = "tablet"
    elif re.search(
        r"Mobile|iPhone|iPod|Android|Windows Phone|BlackBerry|IEMobile|Opera Mini",
        ua,
    ):
        device_type = "mobile"
    else:
        device_type = "desktop"
    parsed["device_type"] = device_type

    return parsed


# ── Client IP extraction ──────────────────────────────────────────────────────

def client_ip_from_request(request) -> Optional[str]:
    """Best-effort client IP.

    Behind Caddy, ``request.client.host`` is the proxy itself, so prefer
    ``X-Forwarded-For``. Caddy appends the real peer to any client-supplied
    value, so the rightmost entry is the one we trust; earlier entries can
    be spoofed. Falls back to X-Real-IP, then the socket peer.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[-1].strip()
        if first:
            return _normalize_ip(first)
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return _normalize_ip(real_ip.strip())
    if request.client and request.client.host:
        return _normalize_ip(request.client.host)
    return None


def _normalize_ip(raw: str) -> Optional[str]:
    """Strip port/zone, unwrap IPv4-mapped IPv6 (``::ffff:1.2.3.4``)."""
    candidate = raw.strip().split("%")[0]
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return candidate if candidate else None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    return str(addr)


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_global


# ── IP geolocation (free, keyless, best-effort) ───────────────────────────────

async def lookup_geo(ip: str) -> Optional[dict]:
    """Coarse geolocation for a public IP. Returns None on any failure —
    this must never block or break signup."""
    if not ip or not _is_public_ip(ip):
        return None

    timeout = httpx.Timeout(GEO_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # ipapi.co: HTTPS, no key needed, ~1000 free lookups/day.
        try:
            resp = await client.get(f"https://ipapi.co/{ip}/json/")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("error"):
                    raise ValueError(data.get("reason", "ipapi.co error"))
                return {
                    "source": "ipapi.co",
                    "country": data.get("country_name"),
                    "country_code": data.get("country_code"),
                    "region": data.get("region"),
                    "city": data.get("city"),
                    "lat": data.get("latitude"),
                    "lon": data.get("longitude"),
                    "timezone": data.get("timezone"),
                    "org": data.get("org"),
                }
        except (httpx.HTTPError, ValueError) as e:
            logger.debug("[signup-meta] ipapi.co failed for %s: %s", ip, e)

        # Fallback: ip-api.com (HTTP-only on the free tier).
        try:
            fields = "status,country,countryCode,regionName,city,lat,lon,timezone,isp,org"
            resp = await client.get(
                f"http://ip-api.com/json/{ip}", params={"fields": fields}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") != "success":
                    return None
                return {
                    "source": "ip-api.com",
                    "country": data.get("country"),
                    "country_code": data.get("countryCode"),
                    "region": data.get("regionName"),
                    "city": data.get("city"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "timezone": data.get("timezone"),
                    "org": data.get("org") or data.get("isp"),
                }
        except httpx.HTTPError as e:
            logger.debug("[signup-meta] ip-api.com failed for %s: %s", ip, e)

    return None


# ── Capture ───────────────────────────────────────────────────────────────────

def _clip_str(value: Any, limit: int = 200) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _clip_num(value: Any, lo: float = 0, hi: float = 100_000) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < lo or num > hi:
        return None
    return num


def build_signup_meta(
    ip: Optional[str],
    geo: Optional[dict],
    user_agent: Optional[str],
    client_payload: dict,
) -> dict:
    """Assemble the ``signup_meta`` record from server + client facts.

    Client-supplied values are treated as untrusted: clamped, truncated,
    and dropped when malformed.
    """
    device = parse_user_agent(user_agent)
    accept_lang = client_payload.pop("_accept_language", None)  # set by caller

    client: dict[str, Any] = {}
    language = _clip_str(client_payload.get("language"), 35) or _clip_str(
        (accept_lang or "").split(",")[0].split(";")[0], 35
    )
    if language:
        client["language"] = language
    timezone_str = _clip_str(client_payload.get("timezone"), 64)
    if timezone_str:
        client["timezone"] = timezone_str
    platform = _clip_str(client_payload.get("platform"), 64)
    if platform:
        client["platform"] = platform
    if isinstance(client_payload.get("touch"), bool):
        client["touch"] = client_payload["touch"]
    screen = client_payload.get("screen")
    if isinstance(screen, dict):
        width = _clip_num(screen.get("w"), 0, 20_000)
        height = _clip_num(screen.get("h"), 0, 20_000)
        dpr = _clip_num(screen.get("dpr"), 0.1, 20)
        if width is not None and height is not None:
            client["screen"] = {
                "w": int(width),
                "h": int(height),
                "dpr": round(dpr, 2) if dpr is not None else None,
            }
    referrer = _clip_str(client_payload.get("referrer"), 500)
    if referrer:
        client["referrer"] = referrer

    meta: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "geo": geo,
        "device": device,
    }
    if client:
        meta["client"] = client
    return meta