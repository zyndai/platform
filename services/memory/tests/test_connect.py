"""Integration tests for the /connect signup page (issues MCP tokens)."""
import pytest

pytestmark = pytest.mark.integration


async def test_connect_form_renders(client):
    r = await client.get("/connect")
    assert r.status_code == 200
    assert 'name="password"' in r.text


async def test_connect_issues_token_and_config(client):
    r = await client.post("/connect", data={"email": "mcpuser@example.com", "password": "strongpass1"})
    assert r.status_code == 200
    assert "mcpServers" in r.text
    assert "Authorization: Bearer" in r.text


async def test_connect_rejects_short_password(client):
    r = await client.post("/connect", data={"email": "x@example.com", "password": "ab"})
    assert r.status_code == 400
