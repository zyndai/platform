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


def test_search_people_claimed_default():
    ask_payload = {
        "query": "AI compliance founders",
        "results": [{
            "handle": "alice",
            "name": "Alice",
            "headline": "Founder",
            "match_score": 0.9,
            "match_reasons": ["Strong overall match for your query", {"type": "memory", "text": "AI compliance"}],
            "claimed": True,
            "url": "https://cards.zynd.ai/p/alice",
        }],
        "numberOfItems": 1,
    }

    async def fake_get(url, params=None):
        assert "/ask" in str(url)
        assert params["include_unclaimed"] is False
        return _FakeResp(ask_payload)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.post = AsyncMock(return_value=_FakeResp({}, status=204))

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        out = asyncio.run(search_people_impl("AI compliance founders", k=5))

    assert out["numberOfItems"] == 1
    hit = out["results"][0]
    assert hit["claimed"] is True
    assert hit["handle"] == "alice"
    assert "Strong overall match" in hit["match_reasons"][0]
    assert "AI compliance" in hit["match_reasons"]
    assert hit["cite_as"].endswith("/p/alice")


def test_search_people_unclaimed_strips_contact():
    ask_payload = {
        "results": [{
            "handle": "bob",
            "name": "Bob",
            "email": "bob@example.com",
            "claimed": False,
            "match_reasons": ["weak"],
            "url": "https://cards.zynd.ai/p/bob",
        }],
    }

    async def fake_get(url, params=None):
        assert params["include_unclaimed"] is True
        return _FakeResp(ask_payload)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.post = AsyncMock(return_value=_FakeResp({}, status=204))

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        out = asyncio.run(search_people_impl("engineer", include_unclaimed=True))

    hit = out["results"][0]
    assert hit["claimed"] is False
    assert "email" not in hit


def test_search_people_uses_agents_search_when_filters():
    seen = {}

    async def fake_get(url, params=None):
        seen["url"] = str(url)
        seen["params"] = params
        return _FakeResp({"results": []})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.post = AsyncMock(return_value=_FakeResp({}, status=204))

    with patch("app.cards_public_mcp.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(search_people_impl("rust", location="Berlin", k=3))

    assert "/v1/agents/search" in seen["url"]
    assert seen["params"]["location"] == "Berlin"


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
