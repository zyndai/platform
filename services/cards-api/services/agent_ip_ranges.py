"""Whether a visitor IP belongs to the AI provider its User-Agent (or MCP client name) claims.

A User-Agent and an MCP clientInfo name are both self-reported: `curl -A ChatGPT-User` reads a
card as "ChatGPT". OpenAI, Anthropic and Perplexity publish the egress ranges of their
user-initiated fetchers, so an AI-read alert (services/ai_read_alerts.py) only goes out when the
visitor IP is inside the claimed provider's list. Agents with no published list (Codex runs on the
user's machine; Zynd-MCP is an anonymous MCP client) are never verified.

Lists are fetched lazily, cached in process for CACHE_TTL_SECONDS, and the last good copy is kept
when a refresh fails. No copy at all means unverified, never an exception: this runs on the alert
pool, and a missing email is the safe failure.
"""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
import httpx

logger = logging.getLogger(__name__)

# Each provider's published list for its fetchers that act on a person's request (checked
# 2026-10-29; all three are {"creationTime": ..., "prefixes": [{"ipv4Prefix"|"ipv6Prefix": ...}]}).
OPENAI_USER_RANGES_URL = "https://openai.com/chatgpt-user.json"
# Anthropic publishes one list for all of its bots, Claude-User included.
ANTHROPIC_RANGES_URL = "https://claude.com/crawling/bots.json"
# perplexity.com redirects here; ask for the target directly.
PERPLEXITY_USER_RANGES_URL = "https://www.perplexity.ai/perplexity-user.json"

AGENT_RANGE_URLS = {
    "ChatGPT-User": OPENAI_USER_RANGES_URL,
    "ChatGPT-MCP": OPENAI_USER_RANGES_URL,
    "Claude-User": ANTHROPIC_RANGES_URL,
    "Claude-MCP": ANTHROPIC_RANGES_URL,
    "Perplexity-User": PERPLEXITY_USER_RANGES_URL,
    "Perplexity-MCP": PERPLEXITY_USER_RANGES_URL,
}

# Who publishes each list, for the alert email. The list belongs to the company, not the product
# name the User-Agent carries: Claude-User is checked against Anthropic's list.
RANGE_PUBLISHERS = {
    OPENAI_USER_RANGES_URL: "OpenAI",
    ANTHROPIC_RANGES_URL: "Anthropic",
    PERPLEXITY_USER_RANGES_URL: "Perplexity",
}

# The providers update these lists rarely; a day keeps us to one fetch per list per worker per day.
CACHE_TTL_SECONDS = 24 * 3600
# After a failed refresh, wait this long before trying that list again instead of paying the
# timeout on every AI read while the provider is down.
RETRY_AFTER_FAILURE_SECONDS = 10 * 60
FETCH_TIMEOUT_SECONDS = 5.0
# Some of these hosts answer 403 to a library's default User-Agent.
FETCH_USER_AGENT = "ZyndCards/1.0 (+https://cards.zynd.ai)"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

_lock = threading.Lock()
# url -> (monotonic time of the last good fetch, its networks)
_cache: dict[str, tuple[float, tuple[Network, ...]]] = {}
# url -> monotonic time before which a failed list is not fetched again
_retry_at: dict[str, float] = {}


def has_published_ranges(agent: str | None) -> bool:
    return (agent or "") in AGENT_RANGE_URLS


def range_publisher(agent: str | None) -> str | None:
    url = AGENT_RANGE_URLS.get(agent or "")
    return RANGE_PUBLISHERS[url] if url else None


def is_provider_ip(agent: str | None, ip: str | None) -> bool:
    """True only when `ip` is inside the published ranges of the provider `agent` names."""
    url = AGENT_RANGE_URLS.get(agent or "")
    address = parse_ip(ip)
    if url is None or address is None:
        return False
    networks = _networks(url)
    return any(address.version == net.version and address in net for net in networks)


def parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    # An IPv4-mapped IPv6 peer ("::ffff:1.2.3.4") is the IPv4 address the lists name.
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped or address


def _networks(url: str) -> tuple[Network, ...]:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(url)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        if _retry_at.get(url, 0.0) > now:
            return cached[1] if cached else ()
    # Fetched outside the lock: a slow provider must not stall checks against the other lists.
    # Two threads may refresh the same list at once; both results are equally good.
    try:
        networks = tuple(fetch_networks(url))
        if not networks:
            raise ValueError("no usable prefixes")
    except Exception as exc:  # noqa: BLE001 — any failure keeps the last good copy
        logger.warning("agent ip ranges refresh failed url=%s err=%s; %s", url, type(exc).__name__,
                       "keeping last good copy" if cached else "alerts unverified until it loads")
        with _lock:
            _retry_at[url] = time.monotonic() + RETRY_AFTER_FAILURE_SECONDS
        return cached[1] if cached else ()
    with _lock:
        _cache[url] = (time.monotonic(), networks)
        _retry_at.pop(url, None)
    return networks


def fetch_networks(url: str) -> list[Network]:
    response = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True,
                         headers={"User-Agent": FETCH_USER_AGENT, "Accept": "application/json"})
    response.raise_for_status()
    return parse_prefixes(response.json())


def parse_prefixes(data: object) -> list[Network]:
    """The prefixes of one published list; entries that do not parse are skipped."""
    prefixes = data.get("prefixes") if isinstance(data, dict) else None
    networks: list[Network] = []
    for entry in prefixes if isinstance(prefixes, list) else []:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("ipv4Prefix") or entry.get("ipv6Prefix")
        if not isinstance(raw, str):
            continue
        try:
            networks.append(ipaddress.ip_network(raw.strip(), strict=False))
        except ValueError:
            continue
    return networks


def reset_cache() -> None:
    with _lock:
        _cache.clear()
        _retry_at.clear()
