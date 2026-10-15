from unittest.mock import AsyncMock
from uuid import UUID
import json
import httpx
import pytest
from app import main
from app.config import settings

UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def pool(monkeypatch):
    pool = AsyncMock()
    monkeypatch.setattr(main, "get_pool", lambda: pool)
    monkeypatch.setattr(settings, "memory_service_token", "identity-service-test")
    monkeypatch.setattr(settings, "s12_identity_issuer", "https://shared.test/auth/v1")
    return pool


async def lookup(headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        return await client.get("/v1/service/identity/" + UID, headers=headers or {})


async def test_identity_requires_service_credential(pool):
    assert (await lookup()).status_code == 401
    pool.fetch.assert_not_called()


async def test_identity_requires_configured_issuer(pool, monkeypatch):
    monkeypatch.setattr(settings, "s12_identity_issuer", "")
    assert (
        await lookup({"Authorization": "Bearer identity-service-test"})
    ).status_code == 503
    pool.fetch.assert_not_called()


async def test_identity_only_resolves_supabase_uuid_not_email(pool):
    pool.fetch.return_value = [
        {"id": UUID("00000000-0000-0000-0000-000000000002"), "supabase_user_id": UID}
    ]
    response = await lookup({"Authorization": "Bearer identity-service-test"})
    assert response.status_code == 200
    assert response.json()["zynd_uid"] == UID
    query, uid = pool.fetch.await_args.args
    assert "WHERE supabase_user_id = $1" in query and "email" not in query
    assert uid == UID
    assert "facts" not in response.json()


@pytest.mark.parametrize("rows,code", [([], 404), ([{"id": "a"}, {"id": "b"}], 409)])
async def test_absent_and_conflicting_links_fail_closed(pool, rows, code):
    pool.fetch.return_value = rows
    assert (
        await lookup({"Authorization": "Bearer identity-service-test"})
    ).status_code == code


def test_owner_intro_tool_requires_cards_read_scope():
    from app.services.mcp_scopes import tool_visible

    assert tool_visible("list_intros", ["cards:read"])
    assert not tool_visible("list_intros", ["memory:write"])
    assert not tool_visible("list_intros", ["people:message"])


async def test_owner_intro_tool_does_not_fall_back_to_email(pool, monkeypatch):
    from app.tools import card_intros

    monkeypatch.setattr(settings, "feature_s12_intros", True)
    pool.fetchval.return_value = None
    result = await card_intros.get_owner_intros(pool, UID)
    assert not result["ok"]
    assert "supabase_user_id" in pool.fetchval.await_args.args[0]
    assert "email" not in pool.fetchval.await_args.args[0]


@pytest.mark.parametrize(
    "scopes,can_read", [(["cards:read"], True), (["memory:write"], False)]
)
async def test_scoped_client_can_authenticate_without_legacy_user_scope(
    monkeypatch, scopes, can_read
):
    from app.auth import issue_client_token
    from app import mcp_http

    db = AsyncMock()
    db.fetchval.side_effect = [1, "client-test"]
    token, _ = await issue_client_token(db, UID, label="S12 test", scopes=scopes)
    db.fetchval.side_effect = None
    db.fetchval.return_value = 1
    db.fetchrow.return_value = {"revoked_at": None, "user_id": UID}
    monkeypatch.setattr(mcp_http, "_get_pool", AsyncMock(return_value=db))
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
    }
    async with mcp_http.app.router.lifespan_context(mcp_http.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mcp_http.app), base_url="http://localhost"
        ) as client:
            initialized = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            assert initialized.status_code == 200, initialized.text
            response = await client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            assert response.status_code == 200, response.text
    data = (
        response.json()
        if "application/json" in response.headers.get("content-type", "")
        else json.loads(
            next(
                line[6:]
                for line in response.text.splitlines()
                if line.startswith("data: ")
            )
        )
    )
    names = {tool["name"] for tool in data["result"]["tools"]}
    assert ("list_intros" in names) == can_read
    assert "search_gmail_emails" not in names
