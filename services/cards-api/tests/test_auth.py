"""Multi-issuer Supabase JWT verification (no network — JWKS lookup is stubbed)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import config
from api.auth import Principal, _jwks_clients, verify_supabase_jwt


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    _jwks_clients.clear()
    yield
    _jwks_clients.clear()


def _es256_token(iss: str, email: str = "alice@example.com", sub: str = "sub-1"):
    private_key = ec.generate_private_key(ec.SECP256R1())
    payload = {"iss": iss, "email": email, "sub": sub, "exp": int(time.time()) + 3600}
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token, private_key.public_key()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._public_key)


def test_trusted_issuer_is_verified_and_returns_principal(monkeypatch):
    import api.auth as auth_module

    issuer_url = "https://aafo.example"
    token, public_key = _es256_token(f"{issuer_url}/auth/v1")
    monkeypatch.setattr(config, "TRUSTED_SUPABASE_URLS", [issuer_url])
    monkeypatch.setattr(auth_module, "_get_jwks_client", lambda url: _FakeJWKClient(public_key))

    principal = verify_supabase_jwt(f"Bearer {token}")

    assert principal == Principal(email="alice@example.com", sub="sub-1", iss=f"{issuer_url}/auth/v1")


def test_second_trusted_issuer_is_also_verified(monkeypatch):
    """Both xmfj and aafo trusted simultaneously — a token from either verifies."""
    import api.auth as auth_module

    xmfj_url = "https://xmfj.example"
    aafo_url = "https://aafo.example"
    token, public_key = _es256_token(f"{xmfj_url}/auth/v1", email="bob@example.com", sub="sub-2")
    monkeypatch.setattr(config, "TRUSTED_SUPABASE_URLS", [xmfj_url, aafo_url])
    monkeypatch.setattr(auth_module, "_get_jwks_client", lambda url: _FakeJWKClient(public_key))

    principal = verify_supabase_jwt(f"Bearer {token}")

    assert principal.email == "bob@example.com"
    assert principal.iss == f"{xmfj_url}/auth/v1"


def test_unmatched_issuer_falls_back_to_hs256_and_fails_without_secret(monkeypatch):
    token, _ = _es256_token("https://untrusted.example/auth/v1")
    monkeypatch.setattr(config, "TRUSTED_SUPABASE_URLS", ["https://aafo.example"])
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "")

    assert verify_supabase_jwt(f"Bearer {token}") is None


def test_unmatched_issuer_falls_back_to_hs256_legacy_secret(monkeypatch):
    # The legacy secret belongs to SUPABASE_URL's project; its tokens carry that issuer.
    monkeypatch.setattr(config, "TRUSTED_SUPABASE_URLS", ["https://aafo.example"])
    monkeypatch.setattr(config, "SUPABASE_URL", "https://xmfj.example")
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "legacy-secret")
    legacy_token = jwt.encode(
        {"email": "legacy@example.com", "sub": "sub-legacy", "iss": "https://xmfj.example/auth/v1"},
        "legacy-secret",
        algorithm="HS256",
    )

    principal = verify_supabase_jwt(f"Bearer {legacy_token}")

    assert principal == Principal(email="legacy@example.com", sub="sub-legacy", iss="https://xmfj.example/auth/v1")


def test_hs256_legacy_token_claiming_another_projects_issuer_is_rejected(monkeypatch):
    """A legacy-secret token must not be able to pose as aafo (whose `sub` gets
    stamped into owner_user_id)."""
    monkeypatch.setattr(config, "TRUSTED_SUPABASE_URLS", ["https://xmfj.example"])
    monkeypatch.setattr(config, "SUPABASE_URL", "https://xmfj.example")
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "legacy-secret")
    forged = jwt.encode(
        {"email": "mallory@example.com", "sub": "sub-x", "iss": "https://aafo.example/auth/v1"},
        "legacy-secret",
        algorithm="HS256",
    )

    assert verify_supabase_jwt(f"Bearer {forged}") is None


def test_no_or_malformed_authorization_header_returns_none():
    assert verify_supabase_jwt(None) is None
    assert verify_supabase_jwt("not-a-bearer-token") is None
