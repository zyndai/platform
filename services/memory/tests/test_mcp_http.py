"""Unit tests for the hosted MCP server's auth provider + tool registration."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import app.mcp_http as hosted
from app.auth import _encode
from app.config import settings
from app.mcp_http import ZyndTokenVerifier
from app.mcp_http import app as mcp_asgi
from app.mcp_http import mcp


async def test_rejects_missing_token():
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/mcp", json={})
        assert r.status_code == 401


async def test_rejects_bad_token():
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/mcp", headers={"Authorization": "Bearer not-a-jwt"}, json={})
        assert r.status_code == 401


@pytest.mark.parametrize("scopes,owner_allowed", [
    (["memory:write"], False),
    (["memory:write", "cards:read"], True),
])
async def test_authenticated_http_discovery_call_and_injection(monkeypatch, scopes, owner_allowed):
    """Exercise HTTP auth and dependency injection, not the in-memory client."""
    monkeypatch.setattr(settings, "jwt_secret", "http-test-secret-0123456789-0123456789")
    pool = AsyncMock()
    pool.fetchval.return_value = 7
    pool.fetchrow.return_value = {
        "display_name": "Alice", "email": "alice@example.com",
        "supabase_user_id": None, "socials": {},
    }
    facts = AsyncMock(return_value=[])
    card = AsyncMock(return_value=[])
    brief = AsyncMock(return_value={"success": True, "content": "Alice's brief"})
    owner = AsyncMock(return_value={"ok": True, "data": {"pending": 2}})
    monkeypatch.setattr(hosted, "_get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(hosted, "active_context", facts)
    monkeypatch.setattr(hosted, "get_card", card)
    monkeypatch.setattr(hosted.brief_tools, "read_my_brief", brief)
    monkeypatch.setattr("app.tools.card_status.get_owner_status", owner)
    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(side_effect=AssertionError("Real DB forbidden")))

    token = _encode("alice", "access", 300, ver=7, scopes=scopes)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }
    http_app = mcp.http_app(path="/mcp", stateless_http=True, allowed_hosts=["localhost"])
    async with http_app.router.lifespan_context(http_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app), base_url="http://localhost:8090",
            headers=headers,
        ) as client:
            async def rpc(request_id, method, params):
                response = await client.post("/mcp", json={
                    "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
                })
                assert response.status_code == 200, response.text
                if "text/event-stream" in response.headers.get("content-type", ""):
                    return json.loads(next(
                        line[6:] for line in response.text.splitlines() if line.startswith("data: ")
                    ))
                return response.json()

            initialized = await rpc(1, "initialize", {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "http-regression", "version": "1"},
            })
            assert initialized["result"]["protocolVersion"] == "2025-11-25"
            response = await client.post("/mcp", json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            assert response.status_code == 202
            tools = (await rpc(2, "tools/list", {}))["result"]["tools"]
            expected = {"get_my_context", "report_user_info", "confirm_fact_tool", "forget_fact_tool"}
            if owner_allowed:
                expected |= {"list_pending_facts", "list_intros"}
            assert {tool["name"] for tool in tools} == expected
            context_tool = next(tool for tool in tools if tool["name"] == "get_my_context")
            assert set(context_tool["inputSchema"]["properties"]) == {"topic", "k"}

            result = (await rpc(3, "tools/call", {
                "name": "get_my_context", "arguments": {"k": 7},
            }))["result"]
            assert not result.get("isError", False), result
            packet = result["structuredContent"]
            assert packet["identity"]["name"] == "Alice"
            assert packet["brief"] == "Alice's brief"
            assert ("status" in packet) is owner_allowed
            assert ("activity" in packet) is owner_allowed
            facts.assert_awaited_once_with(pool, "alice", 7)
            card.assert_awaited_once_with(pool, "alice")
            brief.assert_awaited_once_with("alice")
            if owner_allowed:
                owner.assert_awaited_once_with(pool, "alice")
            else:
                owner.assert_not_awaited()

            denied = await rpc(4, "tools/call", {"name": "export_my_context", "arguments": {}})
            assert "error" in denied
            assert "not granted" in denied["error"]["message"]
            facts.reset_mock()
            card.reset_mock()
            owner.reset_mock()
            spoofed = await rpc(5, "tools/call", {
                "name": "get_my_context",
                "arguments": {"k": 7, "uid": "bob", "token": {"scopes": ["user"]}},
            })
            # SDK versions may reject undeclared arguments or ignore them; neither may override auth.
            if "error" in spoofed or spoofed.get("result", {}).get("isError"):
                facts.assert_not_awaited()
                card.assert_not_awaited()
                owner.assert_not_awaited()
            else:
                spoofed_packet = spoofed["result"]["structuredContent"]
                assert spoofed_packet["identity"]["name"] == "Alice"
                assert ("status" in spoofed_packet) is owner_allowed
                assert ("activity" in spoofed_packet) is owner_allowed
                facts.assert_awaited_once_with(pool, "alice", 7)
                card.assert_awaited_once_with(pool, "alice")
                if owner_allowed:
                    owner.assert_awaited_once_with(pool, "alice")
                else:
                    owner.assert_not_awaited()


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"get_my_context", "export_my_context", "find_similar_users", "find_people",
             "confirm_fact_tool", "forget_fact_tool", "report_user_info",
             "request_card_intro", "create_group", "invite_to_group",
             "send_persona_message", "message_zynd_agent"} <= names
    assert names.isdisjoint({
        "remember", "get_my_card", "get_my_socials", "read_my_brief",
        "get_my_system_prompt", "get_card_status", "get_card_activity",
    })


async def test_opaque_token_revoked_after_watermark():
    """An opaque OAuth token minted at or before tokens_revoked_at is rejected."""
    verifier = ZyndTokenVerifier()
    created = datetime.now(timezone.utc) - timedelta(seconds=10)
    pool = AsyncMock()
    pool.fetchrow.return_value = {
        "user_id": "user-1", "scopes": ["user"], "created_at": created,
        "tokens_revoked_at": datetime.now(timezone.utc),
    }
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        assert await verifier.verify_token("opaque-token") is None


async def test_opaque_token_accepted_when_not_revoked():
    verifier = ZyndTokenVerifier()
    pool = AsyncMock()
    pool.fetchrow.return_value = {
        "user_id": "user-1", "scopes": ["user"],
        "created_at": datetime.now(timezone.utc) - timedelta(seconds=10),
        "tokens_revoked_at": None,
    }
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await verifier.verify_token("opaque-token")
    assert result is not None
    assert result.client_id == "user-1"


async def test_oauth_protected_resource():
    """FastMCP's RemoteAuthProvider exposes the well-known OAuth endpoint.

    The protected-resource metadata is path-scoped (RFC 9728 §3.1), so it is
    served at /.well-known/oauth-protected-resource/<mcp path>.
    """
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/.well-known/oauth-protected-resource/mcp")
        assert r.status_code == 200
        data = r.json()
        assert "authorization_servers" in data
        assert len(data["authorization_servers"]) >= 1
        assert "/mcp/mcp" not in data["resource"]
        assert data["resource"].rstrip("/").endswith("/mcp")
