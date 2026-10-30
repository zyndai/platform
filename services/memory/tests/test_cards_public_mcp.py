"""S11 public Cards MCP — tool wrappers + mapping (cards-api HTTP mocked)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import Client
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import cards_public_mcp as pub
from app.cards_public_mcp import (
    RateLimitMiddleware,
    ask_card_impl,
    coarse_query_category,
    get_card_impl,
    mcp,
    search_people_impl,
)


@pytest.fixture(autouse=True)
def _enable_and_clear(monkeypatch):
    monkeypatch.setattr(pub.settings, "feature_s11_public_mcp", True)
    monkeypatch.setattr(pub.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(pub.settings, "cards_site_base_url", "https://cards.zynd.ai")
    monkeypatch.setattr(pub.settings, "s11_get_card_cache_ttl_seconds", 0)
    pub.clear_caches()
    yield
    pub.clear_caches()


def test_tools_and_prompt_registered():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"search_people", "get_card", "ask_card"}
    prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert "find-people" in prompts
    templates = asyncio.run(mcp.list_resource_templates())
    assert any("zynd://card/{handle}" in str(t.uri_template) for t in templates)


def test_tool_descriptions_say_when_to_use():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ("search_people", "get_card", "ask_card"):
        desc = (tools[name].description or "").lower()
        assert "when to use" in desc


def test_flag_off_rejects():
    with patch.object(pub.settings, "feature_s11_public_mcp", False):
        with pytest.raises(RuntimeError, match="not enabled"):
            asyncio.run(search_people_impl("AI founders"))


def test_coarse_query_category():
    assert coarse_query_category("AI compliance founders") == "founder"
    assert coarse_query_category("senior Rust engineer") == "engineer"
    assert coarse_query_category("xyzzy") == "other"
    assert coarse_query_category("") == "empty"


class _FakeResp:
    def __init__(self, data, status=200, content=None, text=None):
        self._data = data
        self.status_code = status
        self.content = content if content is not None else json.dumps(data).encode()
        self.text = text if text is not None else (
            content.decode() if isinstance(content, (bytes, bytearray)) else json.dumps(data)
        )

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "http://cards.test/")
            raise httpx.HTTPStatusError("err", request=req, response=self)


def _cards_http(handler, calls=None):
    """Patch httpx so Cards answers `handler(url, params) -> payload` (a dict) or raises."""
    async def fake_get(url, params=None):
        if calls is not None:
            calls.append((str(url), dict(params or {})))
        return _FakeResp(handler(str(url), dict(params or {})))

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.post = AsyncMock(return_value=_FakeResp({}, status=204))
    return patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client)


ALICE = {
    "handle": "alice", "name": "Alice", "headline": "Founder", "location": "Pune, India", "skills": ["compliance"],
    "industries": ["AI"], "availability": "open", "match_score": 0.9, "claimed": True,
    "match_reasons": ["Strong overall match for your query", {"type": "memory", "text": "AI compliance", "age_days": 2}],
    "fresh_as_of": "2026-10-20T00:00:00Z", "url": "https://cards.zynd.ai/p/alice",
}


def test_search_people_claimed_default():
    calls = []
    with _cards_http(lambda url, params: {"results": [ALICE]}, calls):
        out = asyncio.run(search_people_impl("AI compliance founders", k=5))

    url, params = calls[0]
    assert "/v1/agents/search" in url and params["include_unclaimed"] == "false"     # claimed cards only
    assert params["role"] == "founder" and params["topics"] and params["relax"] == "true"
    assert out["numberOfItems"] == 1 and out["intent"] == "target"
    hit = out["results"][0]
    # Every key the tool has always returned is still there, filled from the Card.
    assert {"handle", "name", "headline", "location", "skills", "industries", "availability", "match_score",
            "match_reasons", "claimed", "fresh_as_of", "url", "cite_as"} <= set(hit)
    assert (hit["handle"], hit["claimed"], hit["industries"], hit["availability"]) == ("alice", True, ["AI"], "open")
    assert hit["fresh_as_of"] == "2026-10-20T00:00:00Z" and hit["cite_as"].endswith("/p/alice")
    assert hit["match_score"] == 0.9 and hit["match_quality"] == "exact"
    # Reasons are specific: the role, and the approved fact with its age; never the generic line.
    assert hit["match_reasons"][0] == "Founder (headline)"
    assert any("AI compliance" in r and "approved fact" in r for r in hit["match_reasons"])
    assert not any("Strong overall match" in r for r in hit["match_reasons"])


def test_search_people_unclaimed_strips_contact():
    bob = {"handle": "bob", "name": "Bob", "email": "bob@example.com", "claimed": False,
           "match_reasons": ["weak"], "url": "https://cards.zynd.ai/p/bob"}
    calls = []
    with _cards_http(lambda url, params: {"results": [bob]}, calls):
        out = asyncio.run(search_people_impl("engineer", include_unclaimed=True))

    assert calls[0][1]["include_unclaimed"] == "true"
    hit = out["results"][0]
    assert hit["claimed"] is False
    assert "email" not in hit and "bob@example.com" not in repr(out)


def test_search_people_uses_agents_search_when_filters():
    calls = []
    with _cards_http(lambda url, params: {"results": []}, calls):
        asyncio.run(search_people_impl("rust", location="Berlin", k=3))

    url, params = calls[0]
    assert "/v1/agents/search" in url
    assert params["location"] == "Berlin"


def test_explicit_filters_are_strict_and_alone():
    """Pinned role, location or skills are the only ones sent and nothing is relaxed; the free text
    only ranks. The parse must not add a role of its own on top of what the caller pinned."""
    calls = []
    with _cards_http(lambda url, params: {"results": []}, calls):
        asyncio.run(search_people_impl("AI investor", location="Berlin", industry="fintech", experience_min=5))
    params = calls[0][1]
    assert params["location"] == "Berlin" and params["industry"] == "fintech" and params["experience_min"] == 5
    assert "role" not in params and "relax" not in params and "skills" not in params


def test_a_search_by_filters_alone_still_has_words_to_rank_by():
    calls = []
    with _cards_http(lambda url, params: {"results": []}, calls):
        out = asyncio.run(search_people_impl("", role="Rust engineer", location="Berlin"))
    assert calls[0][1]["q"] == "Rust engineer Berlin" and calls[0][1]["role"] == "Rust engineer"
    assert out["numberOfItems"] == 0 and "error" not in out
    assert asyncio.run(search_people_impl("", k=3))["error"] == "query required"


def test_a_name_is_looked_up_as_a_name():
    chandan = {"handle": "chandan-kumar-2en8", "name": "Chandan Kumar", "headline": "Founder", "claimed": True,
               "match_score": 0.389, "url": "https://cards.zynd.ai/p/chandan-kumar-2en8"}
    calls = []
    with _cards_http(lambda url, params: {"results": [chandan]} if "/lookup" in url else {"results": []}, calls):
        out = asyncio.run(search_people_impl("Chandan Kumar"))
    assert "/v1/agents/lookup" in calls[0][0] and calls[0][1]["name"] == "Chandan Kumar"
    assert calls[0][1]["include_unclaimed"] == "false" and len(calls) == 1
    assert out["intent"] == "name" and [r["handle"] for r in out["results"]] == ["chandan-kumar-2en8"]
    assert out["results"][0]["match_quality"] == "exact"


def test_a_loosened_search_says_so():
    near = {**ALICE, "handle": "near", "location": "Berlin", "relaxed": ["location"],
            "match_reasons": ["Not in India (closest match)"]}
    with _cards_http(lambda url, params: {"results": [near]}):
        out = asyncio.run(search_people_impl("founder in India"))
    (hit,) = out["results"]
    assert hit["relaxed"] == ["location"] and hit["match_quality"] != "exact"
    assert "Not in India (closest match)" in hit["match_reasons"]
    assert out["note"]                                            # "call them the closest matches"


def test_the_public_tool_never_pays_for_linkedin_or_a_model_call_or_reads_zynd_members():
    from unittest.mock import patch as _patch
    with _cards_http(lambda url, params: {"results": []}), \
            _patch("app.services.people_discovery.search_quickenrich", AsyncMock()) as linkedin, \
            _patch("app.services.people_search.parse_target", AsyncMock()) as model_parse, \
            _patch("app.services.people_search._zynd_people", AsyncMock()) as zynd:
        out = asyncio.run(search_people_impl("seed investor who backs AI dev tools in India"))
    linkedin.assert_not_awaited(); model_parse.assert_not_awaited(); zynd.assert_not_awaited()
    assert out["numberOfItems"] == 0 and "warnings" not in out


def test_a_cards_outage_is_an_error_not_an_empty_answer():
    def down(url, params):
        raise httpx.ConnectError("down")
    with _cards_http(down), pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(search_people_impl("founders"))


def test_get_card_view():
    view = {
        "handle": "alice",
        "claimed": True,
        "identity": {"name": "Alice"},
        "facts": [{"predicate": "has_skill", "object": "Rust"}],
        "cite_as": "https://cards.zynd.ai/p/alice",
        "fresh_as_of": "2026-01-01T00:00:00Z",
        "email": "secret@example.com",
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=_FakeResp(view))
    mock_client.post = AsyncMock(return_value=_FakeResp({}, status=204))

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        # claimed cards keep calendly etc from view; email still stripped by policy?
        # Plan: strip contact only when unclaimed. Claimed may retain calendly.
        out = asyncio.run(get_card_impl("alice"))

    assert out["handle"] == "alice"
    assert out["fresh_as_of"]
    assert out["cite_as"].endswith("/p/alice")
    assert out["cache_control"] == "no-store"  # fixture sets ttl=0
    # Memory's own fetch of the card is labelled so cards-api can tell it from the agent's read.
    assert mock_client.get.await_args.kwargs["headers"]["User-Agent"] == "Zynd-Memory/1.0"


def test_get_card_cache_control_and_hit(monkeypatch):
    monkeypatch.setattr(pub.settings, "s11_get_card_cache_ttl_seconds", 60)
    view = {
        "handle": "alice",
        "claimed": True,
        "cite_as": "https://cards.zynd.ai/p/alice",
        "fresh_as_of": "2026-01-01T00:00:00Z",
    }
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=_FakeResp(view))
    mock_client.post = AsyncMock(return_value=_FakeResp({}, status=204))

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        first = asyncio.run(get_card_impl("alice"))
        second = asyncio.run(get_card_impl("alice"))

    assert first["cache_control"] == "public, max-age=60"
    assert second["cache_control"] == "public, max-age=60"
    assert mock_client.get.await_count == 1
    assert mock_client.post.await_count == 2  # Cached reads still count.
    assert all("Zynd-MCP" in call.kwargs["headers"]["User-Agent"]
               for call in mock_client.post.await_args_list)


def test_get_card_404():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=_FakeResp({"detail": "missing"}, status=404))

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="not found"):
            asyncio.run(get_card_impl("nope"))


def test_ask_card_drains_sse():
    sse = (
        'data: {"response": "Hello "}\n\n'
        'data: {"response": "Alice"}\n\n'
        "data: [DONE]\n\n"
    )
    resp = _FakeResp({}, status=200, content=sse.encode(), text=sse)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        out = asyncio.run(ask_card_impl("alice", "Who are you?"))

    assert out["answer"] == "Hello Alice"
    assert out["labelled"] == "assistant"
    assert out["cite_as"].endswith("/p/alice")


def test_ask_card_unclaimed_403():
    resp = _FakeResp({"detail": "unclaimed"}, status=403)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="unclaimed"):
            asyncio.run(ask_card_impl("bob", "hi"))


def test_find_people_prompt_mentions_tools():
    text = pub.find_people_prompt("AI founders")
    assert "search_people" in text
    assert "get_card" in text
    assert "ask_card" in text
    assert "request_intro" not in text


async def test_removed_public_intro_cannot_be_called():
    async with Client(mcp) as client:
        result = await client.call_tool("request_intro", {}, raise_on_error=False)
    assert result.is_error
    assert "Unknown tool" in result.content[0].text


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_real_mcp_sessions_keep_their_identity_on_cached_reads(monkeypatch, mode):
    from mcp.types import Implementation

    monkeypatch.setattr(pub.settings, "s11_get_card_cache_ttl_seconds", 60)
    upstream = AsyncMock(return_value={"handle": "alice", "claimed": True})
    monkeypatch.setattr(pub, "_http_get", upstream)
    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)
    http.post = AsyncMock(return_value=_FakeResp({}, status=204))
    monkeypatch.setattr(pub.httpx, "AsyncClient", lambda **kw: http)
    for name in ("codex-mcp-client", "claude-ai"):
        async with Client(mcp, client_info=Implementation(name=name, version="test"), mode=mode) as client:
            result = await client.call_tool("get_card", {"handle": "alice"})
            assert not result.is_error
    assert upstream.await_count == 1
    assert [c.kwargs["headers"]["User-Agent"] for c in http.post.await_args_list] == ["Codex", "Claude-MCP"]


def test_merged_app_carries_auth_middleware():
    """S11 route-merge must keep _auth_app's middleware: without it, /mcp's
    RequireAuthMiddleware never sees scope["user"] (set by
    AuthenticationMiddleware → BearerAuthBackend → ZyndTokenVerifier) and every
    authenticated request 401s as invalid_token before the verifier runs.

    Runs in a subprocess: importing app.mcp_http with the flag on in-process
    would leak a duplicate module into sys.modules and break later
    patch("app.mcp_http.…") targets in this test session.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    service_root = str(Path(__file__).resolve().parents[1])
    code = (
        "import os, json, sys\n"
        f"sys.path.insert(0, {service_root!r})\n"
        "os.environ['FEATURE_S11_PUBLIC_MCP'] = 'true'\n"
        "from starlette.middleware.authentication import AuthenticationMiddleware\n"
        "from app.cards_public_mcp import RateLimitMiddleware\n"
        "import app.mcp_http\n"
        "names = [mw.cls.__name__ for mw in app.mcp_http.app.user_middleware]\n"
        "print(json.dumps({'auth': AuthenticationMiddleware.__name__ in names,\n"
        "                 'rate': RateLimitMiddleware.__name__ in names}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=service_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["auth"] is True
    assert result["rate"] is True


def _public_mcp_app():
    async def ok(_request):
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/cards-public-mcp", ok, methods=["POST", "GET"]),
            Route("/mcp", ok, methods=["POST", "GET"]),
        ],
        middleware=[Middleware(RateLimitMiddleware)],
    )


def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setattr(pub.settings, "feature_s11_public_mcp", True)
    monkeypatch.setattr(pub.settings, "s11_rate_limit_per_minute", 2)
    monkeypatch.setattr(pub.settings, "s11_get_card_cache_ttl_seconds", 30)
    pub.clear_caches()
    client = TestClient(_public_mcp_app())
    headers = {"user-agent": "s11-test-ua", "x-forwarded-for": "203.0.113.9"}
    assert client.post("/cards-public-mcp", headers=headers).status_code == 200
    assert client.post("/cards-public-mcp", headers=headers).status_code == 200
    limited = client.post("/cards-public-mcp", headers=headers)
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"] == "rate_limited"
    assert "slow down" in body["message"].lower()
    assert limited.headers.get("retry-after") == "60"
    assert limited.headers.get("cache-control") == "no-store"


def test_rate_limit_skips_personal_mcp(monkeypatch):
    monkeypatch.setattr(pub.settings, "feature_s11_public_mcp", True)
    monkeypatch.setattr(pub.settings, "s11_rate_limit_per_minute", 1)
    pub.clear_caches()
    client = TestClient(_public_mcp_app())
    headers = {"user-agent": "s11-test-ua", "x-forwarded-for": "203.0.113.10"}
    assert client.post("/mcp", headers=headers).status_code == 200
    assert client.post("/mcp", headers=headers).status_code == 200
    assert client.post("/mcp", headers=headers).status_code == 200


def test_rate_limit_sets_cache_control_on_ok(monkeypatch):
    monkeypatch.setattr(pub.settings, "feature_s11_public_mcp", True)
    monkeypatch.setattr(pub.settings, "s11_rate_limit_per_minute", 10)
    monkeypatch.setattr(pub.settings, "s11_get_card_cache_ttl_seconds", 45)
    pub.clear_caches()
    client = TestClient(_public_mcp_app())
    resp = client.post(
        "/cards-public-mcp",
        headers={"user-agent": "s11-cc", "x-forwarded-for": "203.0.113.11"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "public, max-age=45"
