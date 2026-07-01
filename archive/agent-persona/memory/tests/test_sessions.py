"""Integration tests for per-user token revocation (sign-out / disconnect)."""
import asyncio

import pytest

from app.auth import issue_access_token
from app.db import get_pool

pytestmark = pytest.mark.integration


async def _user(email: str) -> str:
    return await get_pool().fetchval(
        """INSERT INTO users (email) VALUES ($1)
           ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id""",
        email)


async def test_logout_revokes_token_then_fresh_token_works(client):
    uid = await _user("logout1@example.com")
    token, _ = issue_access_token(str(uid))
    H = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/me/graph", headers=H)).status_code == 200   # valid before

    await asyncio.sleep(1.1)   # ensure the token's iat second < the sign-out second
    assert (await client.post("/me/logout", headers=H)).status_code == 200

    assert (await client.get("/me/graph", headers=H)).status_code == 401    # same token now dead

    token2, _ = issue_access_token(str(uid))   # a token minted AFTER sign-out is valid again
    assert (await client.get("/me/graph",
                             headers={"Authorization": f"Bearer {token2}"})).status_code == 200


async def test_revocation_is_per_user(client):
    a = await _user("rev_a@example.com")
    b = await _user("rev_b@example.com")
    ta, _ = issue_access_token(str(a))
    tb, _ = issue_access_token(str(b))

    await asyncio.sleep(1.1)
    await client.post("/me/logout", headers={"Authorization": f"Bearer {ta}"})

    assert (await client.get("/me/graph",
                             headers={"Authorization": f"Bearer {ta}"})).status_code == 401  # A out
    assert (await client.get("/me/graph",
                             headers={"Authorization": f"Bearer {tb}"})).status_code == 200  # B fine
