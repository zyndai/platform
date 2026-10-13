"""Unit tests for the MCP connector OAuth flow (no DB/Redis needed).

Covers the RFC 8707 resource indicator, the self-hosted auth page routing, the
lookup-only (never-create) user resolution for connectors, token audience/iss
binding + resource echo, refresh-token rotation, RFC 9207 iss echo, and the
skills shipped with the connector.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi import HTTPException

from app import oauth
from app.auth import issue_rotating_refresh_token
from app.config import settings
from app.mcp_http import ZyndTokenVerifier
from app.mcp_http import app as mcp_asgi
from app.mcp_http import mcp

# The canonical RFC 8707 resource indicator comes from settings so the tests
# hold regardless of how the suite configures MCP_PUBLIC_BASE_URL.
RESOURCE = settings.mcp_resource_url
CALLBACK = "https://chatgpt.com/connector/oauth/abc123"


class FakeRedis:
    """Minimal arq-shaped Redis stand-in: get/set/delete keyed by str."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value.encode()

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _req(fake_redis):
    return type("Req", (), {"app": type("App", (), {"state": type("State", (), {"arq": fake_redis})()})()})


def _pool(rows_by_query: dict[str, list] | None = None) -> AsyncMock:
    rows_by_query = rows_by_query or {}
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(side_effect=lambda q, *a: rows_by_query.get(q, [{"id": 1}])[0])
    return pool


def _sealed(req_jwt: str) -> dict:
    return jwt.decode(req_jwt, settings.jwt_secret, algorithms=["HS256"])


# ── Authorize: resource validation + connector vs legacy routing ───────────────

@patch("app.oauth.get_pool")
async def test_authorize_connector_client_goes_to_self_hosted_auth_page(pool_mock):
    pool = _pool({"SELECT allowed_redirect_uris FROM oauth_clients WHERE client_id = $1": [
        {"allowed_redirect_uris": [CALLBACK]}]})
    pool_mock.return_value = pool
    resp = await oauth.authorize(
        client_id="dcr-client-1", redirect_uri=CALLBACK, state="s1",
        code_challenge="ch", code_challenge_method="S256", resource=RESOURCE,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(f"{settings.public_base_url.rstrip('/')}/oauth/login?zynd_oauth=")
    req = _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])
    assert req["resource"] == RESOURCE
    assert req["create_user"] is False


@patch("app.oauth._fetch_metadata_document")
async def test_authorize_cimd_client_goes_to_auth_page(meta_mock):
    meta_mock.return_value = {
        "client_id": "https://chatgpt.com/connector-client",
        "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
    }
    resp = await oauth.authorize(
        client_id="https://chatgpt.com/connector-client",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        code_challenge="ch", code_challenge_method="S256", resource=RESOURCE,
    )
    assert resp.status_code == 302
    assert "/oauth/login?" in resp.headers["location"]


@patch("app.oauth.get_pool")
async def test_authorize_known_client_uses_auth_page_with_create(pool_mock):
    pool_mock.return_value = AsyncMock()
    resp = await oauth.authorize(
        client_id=settings.oauth_client_id,
        redirect_uri="https://chatgpt.com/aip/plugin-xyz/oauth/callback",
        state="s1", resource=RESOURCE,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(f"{settings.public_base_url.rstrip('/')}/oauth/login?zynd_oauth=")
    req = _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])
    assert req["create_user"] is True


async def test_authorize_rejects_unknown_resource():
    with pytest.raises(HTTPException) as exc:
        await oauth.authorize(
            client_id=settings.oauth_client_id,
            redirect_uri="https://chatgpt.com/aip/plugin-xyz/oauth/callback",
            resource="https://evil.example/mcp",
        )
    assert exc.value.status_code == 400


def test_chatgpt_stable_redirect_allowlisted():
    oauth._check_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect")


# ── Complete: lookup-only for connectors, RFC 9207 iss echo ───────────────────

@patch("app.oauth.get_pool")
@patch("app.services.persona.link_user", new_callable=AsyncMock, return_value=None)
@patch("app.services.users.find_user", new_callable=AsyncMock, return_value=None)
@patch("app.oauth.supabase_identity", new_callable=AsyncMock, return_value=("u@example.com", "U", "sub-1"))
async def test_complete_connector_unknown_user_rejected(identity_mock, find_mock, link_mock, pool_mock):
    pool_mock.return_value = AsyncMock()
    req = oauth._sign_oauth_request(
        CALLBACK, "s1", "ingest", "ch", "S256",
        resource=RESOURCE, create_user=False, iss_supported=True,
    )
    body = oauth._CompleteRequest(req=req, supabase_token="t")
    with pytest.raises(HTTPException) as exc:
        await oauth.complete(_req(FakeRedis()), body)
    assert exc.value.status_code == 401
    assert "No ZYND account found" in exc.value.detail


@patch("app.oauth.get_pool")
@patch("app.services.persona.link_user", new_callable=AsyncMock, return_value=None)
@patch("app.services.users.find_user", new_callable=AsyncMock, return_value="u-1")
@patch("app.oauth.supabase_identity", new_callable=AsyncMock, return_value=("u@example.com", "U", "sub-1"))
async def test_complete_connector_known_user_mints_bound_code_with_iss(identity_mock, find_mock, link_mock, pool_mock):
    pool_mock.return_value = AsyncMock()
    redis = FakeRedis()
    req = oauth._sign_oauth_request(
        CALLBACK, "s1", "ingest", "ch", "S256",
        resource=RESOURCE, create_user=False, iss_supported=True,
    )
    body = oauth._CompleteRequest(req=req, supabase_token="t")
    resp = await oauth.complete(_req(redis), body)
    url = json.loads(resp.body)["redirect_url"]
    assert url.startswith(CALLBACK)
    assert "iss=" in url  # RFC 9207 echo (URL-encoded in the query string)
    assert "code=" in url and "state=s1" in url
    code = url.split("code=", 1)[1].split("&", 1)[0]
    stored = json.loads(redis.store[f"oauth:code:{code}"].decode())
    assert stored["resource"] == RESOURCE
    assert stored["user_id"] == "u-1"


# ── Token: resource echo + audience binding + refresh rotation ────────────────

def _store_connector_code(redis: FakeRedis, code: str) -> None:
    redis.store[f"oauth:code:{code}"] = json.dumps({
        "user_id": "u-1", "redirect_uri": CALLBACK, "resource": RESOURCE,
    }).encode()


async def test_token_connector_code_echoes_resource_and_binds_audience():
    redis = FakeRedis()
    _store_connector_code(redis, "c1")
    with patch("app.oauth.get_pool", return_value=_pool({})):
        resp = await oauth.token(
            _req(redis), grant_type="authorization_code", client_id="dcr-client-1",
            client_secret="", code="c1", redirect_uri=CALLBACK, code_verifier="",
            resource=RESOURCE, scope="",
        )
    assert resp.body  # JSONResponse
    data = json.loads(resp.body)
    assert data["resource"] == RESOURCE
    assert data["token_type"] == "Bearer"
    claims = jwt.decode(data["access_token"], settings.jwt_secret, algorithms=["HS256"],
                        options={"verify_aud": False, "verify_iss": False})
    assert claims["iss"] == settings.public_base_url.rstrip("/")
    assert claims["aud"] == RESOURCE
    assert claims["scp"] == ["user"]
    refresh_jti = jwt.decode(data["refresh_token"], settings.jwt_secret, algorithms=["HS256"],
                             options={"verify_aud": False, "verify_iss": False})["jti"]
    assert f"oauth:refresh:{refresh_jti}" in redis.store


async def test_token_connector_code_rejects_wrong_resource():
    redis = FakeRedis()
    _store_connector_code(redis, "c1")
    with patch("app.oauth.get_pool", return_value=_pool({})):
        with pytest.raises(HTTPException) as exc:
            await oauth.token(
                _req(redis), grant_type="authorization_code", client_id="dcr-client-1",
                client_secret="", code="c1", redirect_uri=CALLBACK, code_verifier="",
                resource="https://other.example/mcp", scope="",
            )
    assert exc.value.status_code == 400


@patch("app.services.sessions.tokens_revoked", new_callable=AsyncMock, return_value=False)
async def test_token_refresh_rotates_and_rejects_replay(revoked_mock):
    redis = FakeRedis()
    refresh_tok, jti = issue_rotating_refresh_token("u-1")
    redis.store[f"oauth:refresh:{jti}"] = RESOURCE.encode()
    with patch("app.oauth.get_pool", return_value=_pool({})):
        resp = await oauth.token(
            _req(redis), grant_type="refresh_token", client_id="dcr-client-1",
            client_secret="", code="", redirect_uri="", code_verifier="",
            refresh_token=refresh_tok, scope="",
        )
        data = json.loads(resp.body)
        assert data["resource"] == RESOURCE
        # Original refresh jti is consumed; a replay must fail.
        with pytest.raises(HTTPException) as exc:
            await oauth.token(
                _req(redis), grant_type="refresh_token", client_id="dcr-client-1",
                client_secret="", code="", redirect_uri="", code_verifier="",
                refresh_token=refresh_tok, scope="",
            )
    assert exc.value.status_code == 400


# ── MCP server: PRM scopes, connector-token acceptance, skills ────────────────

async def test_prm_advertises_user_scope():
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    assert r.json()["scopes_supported"] == ["user"]


@patch("app.services.sessions.token_rejected", new_callable=AsyncMock, return_value=False)
async def test_verifier_accepts_connector_token(rejected_mock):
    from app.auth import issue_connector_access_token
    pool = AsyncMock()
    token, _ = issue_connector_access_token("u-1", settings.mcp_resource_url)
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await ZyndTokenVerifier().verify_token(token)
    assert result is not None
    assert result.client_id == "u-1"
    # RFC 8707 binding: newer FastMCP releases reject tokens whose `resource`
    # doesn't match the resource-server URL.
    assert result.resource == settings.mcp_resource_url
    assert result.expires_at is not None


@patch("app.services.sessions.token_rejected", new_callable=AsyncMock, return_value=False)
async def test_verifier_rejects_connector_token_for_wrong_resource(rejected_mock):
    from app.auth import issue_connector_access_token
    token, _ = issue_connector_access_token("u-1", "https://evil.example/mcp")
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=None)
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await ZyndTokenVerifier().verify_token(token)
    assert result is None


def test_connector_ships_skills():
    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "skill://zynd-memory/SKILL.md" in uris
    assert "skill://zynd-context/SKILL.md" in uris
    assert "skill://zynd-card/SKILL.md" in uris