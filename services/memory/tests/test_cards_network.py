from unittest.mock import AsyncMock

import httpx
import pytest

from app.tools import cards_network as network


USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def bridge(monkeypatch):
    pool = AsyncMock()
    pool.fetchrow.return_value = {"supabase_user_id": USER}
    monkeypatch.setattr(network.settings, "cards_api_url", "http://cards.test")
    monkeypatch.setattr(network.settings, "memory_service_token", "bridge-test-token")
    requests = []
    responses = []
    def handle(request):
        requests.append(request)
        return responses.pop(0) if responses else httpx.Response(200, json={"connections": []})
    client = httpx.AsyncClient
    monkeypatch.setattr(network.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    return pool, requests, responses


async def test_bridge_uses_linked_account_not_memory_identity(bridge):
    pool, requests, _ = bridge
    result = await network.connections(pool, "memory-user")
    assert result == {"ok": True, "connections": []}
    assert requests[0].headers["X-Zynd-User"] == USER
    assert requests[0].headers["Authorization"] == "Bearer bridge-test-token"
    assert requests[0].url.path == "/cards/network/connections"


@pytest.mark.parametrize("row", [None, {"supabase_user_id": None}, {"supabase_user_id": "not-a-uuid"}])
async def test_bridge_rejects_unlinked_identity_without_http(bridge, row):
    pool, requests, _ = bridge
    pool.fetchrow.return_value = row
    assert (await network.connections(pool, USER))["ok"] is False
    assert requests == []


async def test_group_search_encodes_query_as_one_parameter(bridge):
    pool, requests, _ = bridge
    query = "Alice & Bob?limit=1"
    await network.group_people(pool, "memory-user", USER, query)
    assert dict(requests[0].url.params) == {"query": query}


@pytest.mark.parametrize("body", [{"detail": "Accept the connection first"}, ["unavailable"]])
async def test_bridge_returns_upstream_errors_without_crashing(bridge, body):
    pool, _, responses = bridge
    responses.append(httpx.Response(409, json=body))
    result = await network.connections(pool, "memory-user")
    assert result["ok"] is False
    assert result["error"] == (body["detail"] if isinstance(body, dict) else "Cards network request failed")
