from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import mcp_analytics as analytics


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
    calls = client.post.await_args_list
    assert [len(c.kwargs["json"]["events"]) for c in calls] == [20, 5]
    assert calls[0].kwargs["headers"] == {"User-Agent": "Codex"}
    client.post.side_effect = httpx.ConnectError("offline")
    await analytics.record_fetches(["alice"], endpoint="memory-mcp", tool="find_people")


async def test_authenticated_find_people_records_only_returned_public_cards(monkeypatch):
    from app import mcp_http as m
    result = {"people": [
        {"handle": "alice", "claimed": True, "sources": ["card"]},
        {"handle": "unclaimed", "claimed": False, "sources": ["card"]},
        {"handle": "private-member", "claimed": True, "sources": ["zynd"]},
        {"handle": None, "sources": ["linkedin"]},
    ]}
    monkeypatch.setattr(m, "_get_pool", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(m.people_search, "find", AsyncMock(return_value=result))
    record = AsyncMock()
    monkeypatch.setattr(analytics, "record_fetches", record)
    assert await m.find_people("private query", uid="private uid") == result
    record.assert_awaited_once_with(["alice"], endpoint="memory-mcp", tool="find_people", category="search_result")
