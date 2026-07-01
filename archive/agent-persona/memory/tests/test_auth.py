"""Unit tests for JWT issue/verify. No I/O."""
import pytest

from app.auth import (
    issue_access_token,
    issue_refresh_token,
    verify_access_token,
    verify_refresh_token,
)


def test_access_token_roundtrip():
    token, expires_in = issue_access_token("user-123")
    assert expires_in > 0
    assert verify_access_token(token) == "user-123"


def test_refresh_token_roundtrip():
    token = issue_refresh_token("user-123")
    assert verify_refresh_token(token) == "user-123"


def test_tampered_token_rejected():
    token, _ = issue_access_token("user-123")
    with pytest.raises(ValueError):
        verify_access_token(token + "x")


def test_access_verifier_rejects_refresh_token():
    # A refresh token must not be usable as an access token (typ claim guards this).
    refresh = issue_refresh_token("user-123")
    with pytest.raises(ValueError):
        verify_access_token(refresh)
