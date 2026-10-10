"""Unit tests for the hosted MCP server's auth provider + tool registration."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx

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


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"get_my_context", "export_my_context", "find_similar_users", "find_people",
            "confirm_fact_tool", "forget_fact_tool", "report_user_info", "get_my_card"} <= names


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
