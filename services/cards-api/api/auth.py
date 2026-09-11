"""JWT verification for Supabase-issued tokens."""
import logging

import jwt

import config

logger = logging.getLogger(__name__)


def verify_supabase_jwt(authorization: str | None) -> str | None:
    """Verify a Supabase Bearer token and return the caller's email.

    Returns None when the header is absent, malformed, expired, or the
    signature does not match SUPABASE_JWT_SECRET.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    if not config.SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET not configured — rejecting all JWT requests")
        return None
    token = authorization[7:]
    try:
        payload = jwt.decode(
            token,
            config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        email: str | None = payload.get("email")
        if not email:
            logger.warning("JWT valid but missing email claim")
        return email
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT invalid: %s", exc)
        return None
