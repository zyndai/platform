"""Unit tests for the hosted MCP server's auth wrapper + tool registration."""
import asyncio

import httpx

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
    assert {"get_my_context", "export_my_context", "find_similar_users",
            "confirm_fact_tool", "forget_fact_tool"} <= names
