"""JWT access/refresh tokens (HS256). The access token is what the ChatGPT
Action sends as `Authorization: Bearer <token>` to /ingest.

Production note: HS256 with a shared secret is fine for a single backend. If
tokens are ever verified by a different service, move to RS256 (asymmetric).

Every ZYND token carries an `aud: "zynd"` claim; verifiers accept only that
audience, so a token minted for one surface cannot work on another. Long-lived
personal tokens additionally embed `ver` (the user's token_version), so minting
a new personal token revokes every older one (see services/sessions.py).
"""
import time

import jwt

from app.config import settings

_ALGO = "HS256"
_AUD = "zynd"


def _encode(user_id: str, token_type: str, ttl_seconds: int, *, ver: int | None = None) -> str:
    now = int(time.time())
    payload: dict = {
        "sub": user_id,
        "iss": settings.jwt_issuer,
        "aud": _AUD,
        "typ": token_type,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if ver is not None:
        payload["ver"] = ver
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def _decode_payload(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[_ALGO], issuer=settings.jwt_issuer,
            # Audience is checked explicitly below so legacy tokens (no `aud`) can
            # default to the one remaining surface; let PyJWT not second-guess it.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise ValueError(f"invalid token: {exc}") from exc
    if payload.get("typ") != expected_type:
        raise ValueError(f"expected {expected_type} token, got {payload.get('typ')!r}")
    # Legacy tokens (pre-audience) carry no aud; default them to the one surface
    # that remains. Drop this shim once JWT_SECRET has been rotated (Issue 2).
    if payload.get("aud", _AUD) != _AUD:
        raise ValueError(f"unexpected audience {payload.get('aud')!r}")
    sub = payload.get("sub")
    if not sub:  # signed but malformed -> ValueError (401), never a KeyError (500)
        raise ValueError("token missing sub claim")
    return payload


def _decode_full(token: str, expected_type: str) -> tuple[str, int]:
    """Return (sub, iat) for a valid token. `iat` (issued-at, unix seconds) lets the
    caller enforce per-user revocation (tokens issued before a sign-out are rejected)."""
    payload = _decode_payload(token, expected_type)
    return payload["sub"], int(payload.get("iat", 0))


def _decode_ver(token: str, expected_type: str) -> tuple[str, int, int | None]:
    """Return (sub, iat, ver) for a valid token. `ver` is the per-user token_version
    embedded in long-lived personal tokens; None for short-lived OAuth tokens."""
    payload = _decode_payload(token, expected_type)
    ver = payload.get("ver")
    return payload["sub"], int(payload.get("iat", 0)), (int(ver) if ver is not None else None)


def _decode(token: str, expected_type: str) -> str:
    return _decode_full(token, expected_type)[0]


def issue_access_token(user_id: str) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    ttl = settings.access_token_ttl_seconds
    return _encode(user_id, "access", ttl), ttl


def issue_refresh_token(user_id: str) -> str:
    return _encode(user_id, "refresh", settings.refresh_token_ttl_seconds)


async def issue_personal_token(pool, user_id: str) -> str:
    """Long-lived access token a user pastes into an MCP client (Claude/Cursor).

    Minting bumps the user's `token_version` and embeds it as `ver`, so a newly
    minted personal token instantly invalidates every older personal token for
    that user (one active long-lived credential per user)."""
    version = await pool.fetchval(
        "UPDATE users SET token_version = token_version + 1 WHERE id = $1 RETURNING token_version",
        user_id,
    )
    return _encode(user_id, "access", settings.mcp_token_ttl_seconds, ver=version)


def verify_access_token(token: str) -> str:
    """Return the user_id (sub). Raises ValueError if invalid/expired/wrong type/aud."""
    return _decode(token, "access")


def verify_access_claims(token: str) -> tuple[str, int, int | None]:
    """(user_id, iat, ver) for a valid access token — for revocation/version-aware
    auth paths. `ver` is None for short-lived OAuth access tokens."""
    return _decode_ver(token, "access")


def verify_refresh_token(token: str) -> str:
    return _decode(token, "refresh")


def verify_refresh_claims(token: str) -> tuple[str, int]:
    """(user_id, iat) for a valid refresh token — for revocation-aware refresh."""
    return _decode_full(token, "refresh")
