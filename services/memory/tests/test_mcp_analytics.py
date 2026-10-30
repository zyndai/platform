from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json

import httpx
import pytest

from app.services import mcp_analytics as analytics


@pytest.fixture(autouse=True)
def fresh_delivery_client(monkeypatch):
    """Each test builds its own shared client from whatever AsyncClient it patched in."""
    monkeypatch.setattr(analytics, "_client", None)
    monkeypatch.setattr(analytics, "_client_loop", None)
    yield
    analytics._pending.clear()


@pytest.mark.parametrize("name,label", [
    ("codex-mcp-client", "Codex"), ("codex_cli_rs", "Codex"),
    ("ChatGPT", "ChatGPT-MCP"), ("claude-ai", "Claude-MCP"),
    ("custom-client", "Zynd-MCP"),
])
def test_client_identity_without_forwarding_credentials(monkeypatch, name, label):
    monkeypatch.setattr(analytics, "get_http_headers", lambda: {"user-agent": "python-httpx", "authorization": "private"})
    monkeypatch.setattr(analytics, "get_context", lambda: SimpleNamespace(
        session=SimpleNamespace(client_params=SimpleNamespace(clientInfo=SimpleNamespace(name=name)))))
    assert analytics.advertised_user_agent() == f"python-httpx {label}"


def test_missing_client_identity_stays_unknown(monkeypatch):
    monkeypatch.setattr(analytics, "get_http_headers", lambda: {"user-agent": "ChatGPT-User/1.0"})
    def missing():
        raise RuntimeError("no session")
    monkeypatch.setattr(analytics, "get_context", missing)
    assert analytics.advertised_user_agent() == "ChatGPT-User/1.0 Zynd-MCP"


async def test_batching_deduplication_and_delivery_failure(monkeypatch):
    monkeypatch.setattr(analytics.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(analytics, "advertised_user_agent", lambda: "Codex")
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(analytics.httpx, "AsyncClient", lambda **kw: client)
    await analytics.record_fetches([f"h{i}" for i in range(25)] + ["h0"], endpoint="memory-mcp", tool="find_people")
    await analytics.drain()
    calls = client.post.await_args_list
    assert [len(c.kwargs["json"]["events"]) for c in calls] == [20, 5]
    assert calls[0].kwargs["headers"] == {"User-Agent": "Codex"}
    client.post.side_effect = httpx.ConnectError("offline")
    await analytics.record_fetches(["alice"], endpoint="memory-mcp", tool="find_people")
    await analytics.drain()


async def test_server_token_is_sent_only_when_configured(monkeypatch):
    monkeypatch.setattr(analytics.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(analytics, "advertised_user_agent", lambda: "Codex")
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(analytics.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(analytics.settings, "events_server_token", "")
    await analytics.record_fetches(["alice"], endpoint="memory-mcp", tool="get_card")
    monkeypatch.setattr(analytics.settings, "events_server_token", "shared-secret")
    await analytics.record_fetches(["alice"], endpoint="memory-mcp", tool="get_card")
    await analytics.drain()
    first, second = (c.kwargs["headers"] for c in client.post.await_args_list)
    assert first == {"User-Agent": "Codex"}
    assert second == {"User-Agent": "Codex", "X-Zynd-Server-Event": "shared-secret"}


@pytest.mark.parametrize("forwarded, peer, expected", [
    ("203.0.113.5", "127.0.0.1", "203.0.113.5"),
    # A caller-supplied entry comes first; Caddy's own is last.
    ("160.79.104.10, 203.0.113.5", "127.0.0.1", "203.0.113.5"),
    ("", "198.51.100.7", "198.51.100.7"),
])
def test_caller_ip_is_the_entry_caddy_wrote(monkeypatch, forwarded, peer, expected):
    monkeypatch.setattr(analytics, "get_http_request", lambda: SimpleNamespace(
        headers={"x-forwarded-for": forwarded}, client=SimpleNamespace(host=peer)))
    assert analytics.caller_ip() == expected


def test_caller_ip_outside_a_request_is_none(monkeypatch):
    def missing():
        raise RuntimeError("No active HTTP request found.")
    monkeypatch.setattr(analytics, "get_http_request", missing)
    assert analytics.caller_ip() is None


def test_caller_ip_travels_only_with_the_server_token(monkeypatch):
    monkeypatch.setattr(analytics, "advertised_user_agent", lambda: "Claude-MCP")
    monkeypatch.setattr(analytics, "caller_ip", lambda: "203.0.113.5")
    monkeypatch.setattr(analytics.settings, "events_server_token", "")
    assert analytics.delivery_headers() == {"User-Agent": "Claude-MCP"}
    monkeypatch.setattr(analytics.settings, "events_server_token", "shared-secret")
    assert analytics.delivery_headers() == {"User-Agent": "Claude-MCP", "X-Zynd-Server-Event": "shared-secret",
                                            "X-Zynd-Client-IP": "203.0.113.5"}


async def test_authenticated_find_people_records_only_returned_public_cards(monkeypatch):
    from app import mcp_http as m
    result = {"people": [
        {"handle": "alice", "claimed": True, "sources": ["card"]},
        {"handle": "unclaimed", "claimed": False, "sources": ["card"]},
        {"handle": "zynd-member", "claimed": True, "sources": ["zynd"]},
        {"handle": "without-claim-metadata", "sources": ["card"]},
        {"handle": None, "sources": ["linkedin"]},
        {"handle": " "},
    ]}
    monkeypatch.setattr(m, "_get_pool", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(m.people_search, "find", AsyncMock(return_value=result))
    record = AsyncMock()
    monkeypatch.setattr(analytics, "record_fetches", record)
    assert await m.find_people("private query", uid="private uid") == result
    record.assert_awaited_once_with(["alice", "unclaimed", "zynd-member", "without-claim-metadata"],
                                   endpoint="memory-mcp", tool="find_people", category="search_result")


@pytest.mark.parametrize("user_agent,expected_label", [
    ("ChatGPT-User/1.0", "ChatGPT-User/1.0 Zynd-MCP"),
    ("custom-mcp-client", "custom-mcp-client Zynd-MCP"),
])
async def test_authenticated_mcp_http_call_delivers_returned_profile_events(monkeypatch, user_agent, expected_label):
    """Exercise auth, tool dispatch, result filtering and the actual HTTP event payload."""
    from app import mcp_http as hosted
    from app.auth import _encode

    pool = AsyncMock()
    pool.fetchval.return_value = 7
    monkeypatch.setattr(hosted, "_get_pool", AsyncMock(return_value=pool))
    result = {"people": [
        {"handle": "saraffa13-811p", "claimed": True, "sources": ["zynd"]},
        {"handle": "saraffa13-811p", "sources": ["card"]},
        {"handle": "other-card", "claimed": False, "sources": ["card"]},
        {"handle": None, "sources": ["linkedin"]},
    ]}
    monkeypatch.setattr(hosted.people_search, "find", AsyncMock(return_value=result))
    monkeypatch.setattr(analytics.settings, "cards_api_base_url", "http://cards.test")
    delivered = []

    def receive(request):
        delivered.append(request)
        return httpx.Response(204)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(analytics.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(receive), **kwargs))
    token = _encode("searcher", "access", 300, ver=7, scopes=["people:message"])
    app = hosted.mcp.http_app(path="/mcp", stateless_http=True, allowed_hosts=["localhost"])
    async with app.router.lifespan_context(app):
        async with real_client(transport=httpx.ASGITransport(app=app), base_url="http://localhost",
                               headers={"Authorization": f"Bearer {token}", "User-Agent": user_agent,
                                        "Accept": "application/json, text/event-stream",
                                        "MCP-Protocol-Version": "2025-11-25"}) as client:
            for request_id in (1, 2):
                response = await client.post("/mcp", json={
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": "find_people", "arguments": {"target": "private search text"}},
                })
                assert response.status_code == 200, response.text
                payload = json.loads(next(line[6:] for line in response.text.splitlines()
                                          if line.startswith("data: "))) if "text/event-stream" in response.headers.get("content-type", "") else response.json()
                assert not payload.get("error"), payload
                assert not payload["result"].get("isError"), payload

    # Repeat calls each count, but a profile duplicated within one result counts once.
    await analytics.drain()
    assert len(delivered) == 2
    for request in delivered:
        assert str(request.url) == "http://cards.test/events"
        assert request.headers["user-agent"] == expected_label
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert [event["handle"] for event in body["events"]] == ["saraffa13-811p", "other-card"]
        assert all(event["event"] == "agent_fetch" and event["meta"]["tool"] == "find_people"
                   for event in body["events"])
        assert "private search text" not in request.content.decode()


async def test_tool_answer_does_not_wait_for_delivery(monkeypatch):
    import asyncio

    monkeypatch.setattr(analytics.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(analytics, "advertised_user_agent", lambda: "Codex")
    release = asyncio.Event()
    delivered = []

    async def slow_post(url, **kwargs):
        await release.wait()
        delivered.append(kwargs["json"])
        return MagicMock()

    client = MagicMock()
    client.post = slow_post
    monkeypatch.setattr(analytics.httpx, "AsyncClient", lambda **kw: client)
    # #when a tool records a read while cards-api is slow
    await asyncio.wait_for(analytics.record_fetches(["alice"], endpoint="memory-mcp", tool="get_card"), timeout=1)
    # #then the call returned first, and the POST still happens afterwards
    assert delivered == [] and len(analytics._pending) == 1
    release.set()
    await analytics.drain()
    assert [e["handle"] for e in delivered[0]["events"]] == ["alice"] and not analytics._pending


async def test_one_client_is_shared_and_closed_on_shutdown(monkeypatch):
    monkeypatch.setattr(analytics.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(analytics, "advertised_user_agent", lambda: "Codex")
    made = []

    def make(**kw):
        client = MagicMock()
        client.post = AsyncMock(return_value=MagicMock())
        client.aclose = AsyncMock()
        made.append(client)
        return client

    monkeypatch.setattr(analytics.httpx, "AsyncClient", make)
    for handle in ("alice", "bob"):
        await analytics.record_fetches([handle], endpoint="memory-mcp", tool="get_card")
    await analytics.drain()
    assert len(made) == 1 and made[0].post.await_count == 2
    await analytics.aclose()
    made[0].aclose.assert_awaited_once()
    assert analytics._client is None


async def test_unexpected_task_failure_is_logged_not_raised(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(analytics.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(analytics, "advertised_user_agent", lambda: "Codex")

    async def broken(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(analytics, "_deliver", broken)
    with caplog.at_level(logging.WARNING):
        await analytics.record_fetches(["alice"], endpoint="memory-mcp", tool="get_card")
        await analytics.drain()
    assert "MCP card analytics task failed: RuntimeError" in caplog.text
    assert not analytics._pending


def test_internal_card_reads_carry_the_token_and_an_internal_label(monkeypatch):
    monkeypatch.setattr(analytics.settings, "events_server_token", "")
    assert analytics.internal_read_headers() == {"User-Agent": "Zynd-Memory/1.0"}
    monkeypatch.setattr(analytics.settings, "events_server_token", "shared-secret")
    assert analytics.internal_read_headers() == {"User-Agent": "Zynd-Memory/1.0", "X-Zynd-Server-Event": "shared-secret"}
