"""Provider egress ranges for AI-read alerts: parsing, matching, caching and failure. The HTTP fetch
is always faked; nothing here reaches the network."""
import ipaddress

import httpx
import pytest

from services import agent_ip_ranges as ranges

ANTHROPIC = ranges.ANTHROPIC_RANGES_URL


@pytest.fixture
def lists(monkeypatch):
    """Fake fetch: each URL answers its entry in `served` (a list of networks, or an exception)."""
    served: dict = {ANTHROPIC: [ipaddress.ip_network("203.0.113.0/28"), ipaddress.ip_network("2001:db8::/32")]}
    calls: list[str] = []
    clock = [1000.0]

    def fetch(url):
        calls.append(url)
        answer = served.get(url, [])
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ranges, "fetch_networks", fetch)
    monkeypatch.setattr(ranges.time, "monotonic", lambda: clock[0])
    ranges.reset_cache()
    yield served, calls, clock
    ranges.reset_cache()


@pytest.mark.parametrize("ip, inside", [
    ("203.0.113.5", True), ("203.0.113.16", False), ("2001:db8::1", True), ("::ffff:203.0.113.5", True),
    (" 203.0.113.5 ", True), ("", False), (None, False), ("203.0.113.5, 10.0.0.1", False), ("localhost", False),
])
def test_matches_only_inside_the_published_ranges(lists, ip, inside):
    assert ranges.is_provider_ip("Claude-User", ip) is inside


@pytest.mark.parametrize("agent", [None, "", "Codex", "Zynd-MCP", "ClaudeBot", "GPTBot"])
def test_agents_without_a_list_are_never_verified_and_fetch_nothing(lists, agent):
    _, calls, _ = lists
    assert ranges.is_provider_ip(agent, "203.0.113.5") is False
    assert calls == []


def test_mcp_labels_use_their_providers_list(lists):
    served, _, _ = lists
    served[ranges.OPENAI_USER_RANGES_URL] = [ipaddress.ip_network("198.51.100.0/28")]
    assert ranges.is_provider_ip("Claude-MCP", "203.0.113.5") is True
    assert ranges.is_provider_ip("ChatGPT-MCP", "198.51.100.5") is True
    assert ranges.is_provider_ip("ChatGPT-MCP", "203.0.113.5") is False


def test_range_publisher_names_the_company_behind_each_list():
    assert ranges.range_publisher("Claude-User") == "Anthropic"
    assert ranges.range_publisher("ChatGPT-MCP") == "OpenAI"
    assert ranges.range_publisher("Perplexity-User") == "Perplexity"
    assert ranges.range_publisher("Codex") is None and ranges.range_publisher(None) is None
    assert set(ranges.RANGE_PUBLISHERS) == set(ranges.AGENT_RANGE_URLS.values())


def test_list_is_cached_for_a_day(lists):
    _, calls, clock = lists
    for _ in range(3):
        ranges.is_provider_ip("Claude-User", "203.0.113.5")
    assert calls == [ANTHROPIC]
    clock[0] += ranges.CACHE_TTL_SECONDS + 1
    ranges.is_provider_ip("Claude-MCP", "203.0.113.5")
    assert calls == [ANTHROPIC, ANTHROPIC]


def test_failed_refresh_keeps_the_last_good_copy(lists):
    served, calls, clock = lists
    assert ranges.is_provider_ip("Claude-User", "203.0.113.5") is True
    clock[0] += ranges.CACHE_TTL_SECONDS + 1
    served[ANTHROPIC] = httpx.ConnectTimeout("slow")
    assert ranges.is_provider_ip("Claude-User", "203.0.113.5") is True
    # The failure is not retried on every read.
    assert ranges.is_provider_ip("Claude-User", "203.0.113.5") is True
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [httpx.ConnectError("offline"), ValueError("not json"), []])
def test_no_copy_at_all_is_unverified_then_retried_later(lists, failure):
    served, calls, clock = lists
    good = served[ANTHROPIC]
    served[ANTHROPIC] = failure
    assert ranges.is_provider_ip("Claude-User", "203.0.113.5") is False
    assert ranges.is_provider_ip("Claude-User", "203.0.113.5") is False
    assert len(calls) == 1
    served[ANTHROPIC] = good
    clock[0] += ranges.RETRY_AFTER_FAILURE_SECONDS + 1
    assert ranges.is_provider_ip("Claude-User", "203.0.113.5") is True


def test_parse_prefixes_skips_junk():
    data = {"creationTime": "2026-10-29T00:00:00", "prefixes": [
        {"ipv4Prefix": "203.0.113.0/28"}, {"ipv6Prefix": "2001:db8::/32"}, {"ipv4Prefix": "not a prefix"},
        {"ipv4Prefix": 7}, "203.0.113.0/24", {}, {"ipv4Prefix": "198.51.100.7/24"},
    ]}
    assert [str(n) for n in ranges.parse_prefixes(data)] == ["203.0.113.0/28", "2001:db8::/32", "198.51.100.0/24"]
    assert ranges.parse_prefixes({"prefixes": "nope"}) == []
    assert ranges.parse_prefixes([]) == []


def test_fetch_sends_an_explicit_user_agent_and_follows_redirects(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs, url=url)
        return httpx.Response(200, json={"prefixes": [{"ipv4Prefix": "203.0.113.0/28"}]},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(ranges.httpx, "get", fake_get)
    assert [str(n) for n in ranges.fetch_networks(ANTHROPIC)] == ["203.0.113.0/28"]
    assert seen["headers"]["User-Agent"] == ranges.FETCH_USER_AGENT
    assert seen["follow_redirects"] is True and seen["timeout"] == ranges.FETCH_TIMEOUT_SECONDS


def test_fetch_raises_on_an_error_status(monkeypatch):
    monkeypatch.setattr(ranges.httpx, "get", lambda url, **kw: httpx.Response(403, request=httpx.Request("GET", url)))
    with pytest.raises(httpx.HTTPStatusError):
        ranges.fetch_networks(ANTHROPIC)
