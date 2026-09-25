"""JWT verification for Supabase-issued tokens.

Supabase now signs user session tokens with ES256 (P-256 ECDSA). The legacy
HS256 shared secret is still accepted for backward compatibility with any
tokens issued before the key rotation (~6 months ago).
"""
import logging

import jwt
from jwt import PyJWKClient

import config

logger = logging.getLogger(__name__)

# Fetches public keys from Supabase JWKS once and caches for 1 hour.
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None and config.SUPABASE_URL:
        _jwks_client = PyJWKClient(
            f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=3600,
        )
    return _jwks_client


def verify_supabase_jwt(authorization: str | None) -> str | None:
    """Verify a Supabase Bearer token and return the caller's email.

    Tries ES256 (current Supabase signing key) first, falls back to the
    legacy HS256 shared secret. Returns None on any failure.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]

    # ES256 path — current Supabase signing key via JWKS
    client = _get_jwks_client()
    if client:
        try:
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
            return email
        except jwt.ExpiredSignatureError:
            logger.debug("JWT expired")
            return None
        except Exception:
            pass  # kid not in JWKS or wrong alg — try HS256 fallback

    # HS256 fallback — legacy shared secret
    if not config.SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET not configured and ES256 verification failed")
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
        return email
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired (HS256)")
        return None
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT invalid: %s", exc)
        return None
