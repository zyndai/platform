"""JWT access/refresh tokens (HS256). The access token is what the ChatGPT
Action sends as `Authorization: Bearer <token>` to /ingest.

Production note: HS256 with a shared secret is fine for a single backend. If
tokens are ever verified by a different service, move to RS256 (asymmetric).
"""
import time

import jwt

from app.config import settings

_ALGO = "HS256"


def _encode(user_id: str, token_type: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iss": settings.jwt_issuer,
        "typ": token_type,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def _decode(token: str, expected_type: str) -> str:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[_ALGO], issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise ValueError(f"invalid token: {exc}") from exc
    if payload.get("typ") != expected_type:
        raise ValueError(f"expected {expected_type} token, got {payload.get('typ')!r}")
    return payload["sub"]


def issue_access_token(user_id: str) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    ttl = settings.access_token_ttl_seconds
    return _encode(user_id, "access", ttl), ttl


def issue_refresh_token(user_id: str) -> str:
    return _encode(user_id, "refresh", settings.refresh_token_ttl_seconds)


def issue_personal_token(user_id: str) -> str:
    """Long-lived access token a user pastes into an MCP client (Claude/Cursor)."""
    return _encode(user_id, "access", settings.mcp_token_ttl_seconds)


def verify_access_token(token: str) -> str:
    """Return the user_id (sub). Raises ValueError if invalid/expired/wrong type."""
    return _decode(token, "access")


def verify_refresh_token(token: str) -> str:
    return _decode(token, "refresh")
