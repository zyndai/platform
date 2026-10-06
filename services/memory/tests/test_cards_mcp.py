"""Unit tests for the cards MCP server (app.cards_mcp) — auth + tool surface."""
import asyncio

import httpx

from app.cards_mcp import app as mcp_asgi
from app.cards_mcp import mcp


async def test_rejects_missing_token():
    # Unlike the main MCP server, there is NO anonymous surface: no token at
    # all must be a hard 401.
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/cards-mcp", json={})
        assert r.status_code == 401


async def test_rejects_bad_token():
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/cards-mcp", headers={"Authorization": "Bearer not-a-jwt"}, json={})
        assert r.status_code == 401


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"report_user_info", "remember", "get_my_context", "get_my_card"}


async def test_oauth_protected_resource():
    """FastMCP serves RFC 9728 metadata, path-scoped to /cards-mcp."""
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/.well-known/oauth-protected-resource/cards-mcp")
        assert r.status_code == 200
        data = r.json()
        assert "authorization_servers" in data
        assert len(data["authorization_servers"]) >= 1


def test_server_named_zynd_cards():
    assert mcp.name == "zynd-cards"
