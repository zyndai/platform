"""Management endpoints enforce OAuth expiry and owned connection revocation."""
import time
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest

from app.auth import issue_connector_access_token
from app.config import settings
from app.main import app


@pytest.mark.parametrize("method,path", [
    ("GET", "/me/mcp/clients"),
    ("DELETE", "/me/mcp/clients/00000000-0000-0000-0000-000000000001"),
    ("POST", "/me/mcp/revoke-all"),
])
async def test_expired_oauth_cannot_manage_connections(method, path):
    now = int(time.time())
    token = jwt.encode({
        "sub": "user-1", "iss": settings.public_base_url.rstrip("/"),
        "aud": settings.mcp_resource_url, "typ": "access", "scp": ["user"],
        "jti": str(uuid.uuid4()), "iat": now - 7200, "exp": now - 3600,
    }, settings.jwt_secret, algorithm="HS256")
    with patch("app.main.get_pool") as pool, patch("app.supabase_auth.supabase_identity", new_callable=AsyncMock) as identity:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(method, path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    pool.assert_not_called()
    identity.assert_not_awaited()


@pytest.mark.parametrize("row", [None, {"revoked_at": "revoked", "user_id": "user-1"},
                                  {"revoked_at": None, "user_id": "another-user"}])
async def test_missing_revoked_or_foreign_connection_cannot_manage(row):
    token, _ = issue_connector_access_token("user-1", settings.mcp_resource_url, str(uuid.uuid4()))
    pool = AsyncMock()
    pool.fetchrow.return_value = row
    with patch("app.main.get_pool", return_value=pool), \
         patch("app.services.sessions.token_rejected", new_callable=AsyncMock, return_value=False), \
         patch("app.supabase_auth.supabase_identity", new_callable=AsyncMock) as identity:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/me/mcp/clients", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    identity.assert_not_awaited()
    pool.execute.assert_not_awaited()


async def test_supabase_session_can_still_manage_connections():
    with patch("app.supabase_auth.supabase_identity", new_callable=AsyncMock,
               return_value=("owner@example.com", "Owner", "supabase-sub")), \
         patch("app.services.users.resolve_user", new_callable=AsyncMock, return_value="user-1"), \
         patch("app.main.get_pool", return_value=AsyncMock()), \
         patch("app.services.mcp_clients.list_clients", new_callable=AsyncMock, return_value=[]) as listing:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/me/mcp/clients", headers={"Authorization": "Bearer valid-supabase-session"})
    assert response.status_code == 200
    assert response.json() == {"clients": []}
    assert listing.await_args.args[1] == "user-1"
