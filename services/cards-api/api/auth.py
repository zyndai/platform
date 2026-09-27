"""JWT verification for Supabase-issued tokens.

Supabase now signs user session tokens with ES256 (P-256 ECDSA). The legacy
HS256 shared secret is still accepted for backward compatibility with any
tokens issued before the key rotation (~6 months ago).

During the xmfj -> aafo migration, cards-api must trust tokens from either
Supabase project (config.TRUSTED_SUPABASE_URLS). The token's `iss` claim
picks which project's JWKS verifies it; `sub` is only meaningful downstream
when the token came from aafo (config.AAFO_ISSUER), since only aafo's
auth.users has rows the owner_user_id FK can reference.
"""
import logging
from typing import NamedTuple

import jwt
from jwt import PyJWKClient

import config

logger = logging.getLogger(__name__)


class Principal(NamedTuple):
    email: str
    sub: str   # only trustworthy against auth.users when iss == config.AAFO_ISSUER
    iss: str


# One JWKS client per trusted issuer URL, fetched and cached lazily.
_jwks_clients: dict[str, PyJWKClient] = {}


def _get_jwks_client(issuer_url: str) -> PyJWKClient:
    if issuer_url not in _jwks_clients:
        _jwks_clients[issuer_url] = PyJWKClient(
            f"{issuer_url}/auth/v1/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=3600,
        )
    return _jwks_clients[issuer_url]


def verify_supabase_jwt(authorization: str | None) -> Principal | None:
    """Verify a Supabase Bearer token and return the caller's identity.

    Tries ES256 (current Supabase signing key) first, matching the token's
    `iss` claim against config.TRUSTED_SUPABASE_URLS to pick the right JWKS.
    Falls back to the legacy HS256 shared secret. Returns None on any failure.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]

    # Peek at `iss` without verifying the signature yet — just to pick which
    # project's JWKS to check against.
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        unverified = {}
    token_iss = unverified.get("iss", "")

    matched_url = next(
        (u for u in config.TRUSTED_SUPABASE_URLS if token_iss == f"{u}/auth/v1"),
        None,
    )

    # ES256 path — current Supabase signing key via JWKS, for a trusted issuer
    if matched_url:
        try:
            client = _get_jwks_client(matched_url)
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )
            email: str | None = payload.get("email")
            if not email:
                logger.warning("JWT valid (ES256) but missing email claim")
                return None
            return Principal(email=email, sub=payload.get("sub", ""), iss=token_iss)
        except jwt.ExpiredSignatureError:
            logger.debug("JWT expired")
            return None
        except Exception:
            pass  # kid not in JWKS or wrong alg — try HS256 fallback

    # HS256 fallback — legacy shared secret, pinned to whichever single
    # project that secret belongs to (not multi-issuer).
    if not config.SUPABASE_JWT_SECRET:
        logger.error("no trusted issuer matched and SUPABASE_JWT_SECRET not configured")
        return None
    try:
        payload = jwt.decode(
            token,
            config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        email = payload.get("email")
        if not email:
            logger.warning("JWT valid (HS256) but missing email claim")
            return None
        return Principal(email=email, sub=payload.get("sub", ""), iss=payload.get("iss", ""))
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired (HS256)")
        return None
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT invalid: %s", exc)
        return None
