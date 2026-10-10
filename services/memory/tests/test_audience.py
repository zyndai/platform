"""Unit tests for token audience (`aud`) and version (`ver`) gating. No DB."""
import time
from unittest.mock import AsyncMock

import jwt
import pytest

from app.auth import issue_access_token, issue_personal_token, verify_access_claims, verify_access_token
from app.config import settings
from app.services.sessions import token_rejected

_ALGO = "HS256"


def _token(claims: dict) -> str:
    base = {"sub": "user-1", "iss": settings.jwt_issuer, "typ": "access",
            "iat": int(time.time()), "exp": int(time.time()) + 3600}
    base.update(claims)
    return jwt.encode(base, settings.jwt_secret, algorithm=_ALGO)


def test_zynd_audience_accepted():
    assert verify_access_token(_token({"aud": "zynd"})) == "user-1"


def test_foreign_audience_rejected():
    for aud in ("cards-mcp", "persona", "evil"):
        with pytest.raises(ValueError):
            verify_access_token(_token({"aud": aud}))
        with pytest.raises(ValueError):
            verify_access_claims(_token({"aud": aud}))


def test_legacy_token_without_audience_defaults_to_zynd():
    # Pre-audience tokens carry no aud; the shim defaults them to "zynd".
    assert verify_access_token(_token({})) == "user-1"


def test_short_lived_access_token_has_no_version():
    token, _ = issue_access_token("user-1")
    _, _, ver = verify_access_claims(token)
    assert ver is None


async def test_personal_token_embeds_version():
    pool = AsyncMock()
    pool.fetchval.return_value = 7
    token = await issue_personal_token(pool, "user-1")
    _, _, ver = verify_access_claims(token)
    assert ver == 7


async def test_token_rejected_when_version_mismatches():
    pool = AsyncMock()
    pool.fetchval.return_value = 7  # current token_version
    assert await token_rejected(pool, "user-1", int(time.time()), ver=6) is True
    assert await token_rejected(pool, "user-1", int(time.time()), ver=7) is False


async def test_token_rejected_short_lived_falls_back_to_watermark():
    # ver=None delegates to the tokens_revoked_at watermark.
    pool = AsyncMock()
    pool.fetchval.return_value = None  # tokens_revoked_at is None → not revoked
    assert await token_rejected(pool, "user-1", int(time.time()), ver=None) is False