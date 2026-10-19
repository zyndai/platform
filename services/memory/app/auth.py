"""JWT access/refresh tokens (HS256). The access token is what the ChatGPT
Action sends as `Authorization: Bearer <token>` to /ingest.

Production note: HS256 with a shared secret is fine for a single backend. If
tokens are ever verified by a different service, move to RS256 (asymmetric).

Every ZYND token carries an `aud: "zynd"` claim; verifiers accept only that
audience, so a token minted for one surface cannot work on another. Long-lived
personal tokens additionally embed `ver` (the user's token_version), so minting
a new personal token revokes every older one (see services/sessions.py).
"""
import secrets
import time

import jwt

from app.config import settings

_ALGO = "HS256"
_AUD = "zynd"


def _encode(
    user_id: str,
    token_type: str,
    ttl_seconds: int,
    *,
    ver: int | None = None,
    jti: str | None = None,
    scopes: list[str] | None = None,
    oauth_client_id: str | None = None,
    iss: str | None = None,
    aud: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict = {
        "sub": user_id,
        "iss": iss or settings.jwt_issuer,
        "aud": aud or _AUD,
        "typ": token_type,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if ver is not None:
        payload["ver"] = ver
    if jti:
        payload["jti"] = jti
    if scopes:
        payload["scp"] = list(scopes)
    if oauth_client_id:
        payload["cid"] = oauth_client_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def _decode_payload(
    token: str,
    expected_type: str,
    *,
    allowed_audiences: list[str] | None = None,
    allowed_issuers: list[str] | None = None,
) -> dict:
    if allowed_issuers is None:
        # Legacy behaviour: exactly one issuer, verified by PyJWT.
        issuers = [settings.jwt_issuer]
        try:
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=[_ALGO], issuer=settings.jwt_issuer,
                # Audience is checked explicitly below so legacy tokens (no `aud`) can
                # default to the one remaining surface; let PyJWT not second-guess it.
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise ValueError(f"invalid token: {exc}") from exc
    else:
        # Multi-issuer acceptance (connector tokens carry the AS issuer, legacy
        # tokens carry jwt_issuer). Verify membership explicitly.
        issuers = allowed_issuers
        try:
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=[_ALGO],
                options={"verify_aud": False, "verify_iss": False},
            )
        except jwt.PyJWTError as exc:
            raise ValueError(f"invalid token: {exc}") from exc
        if payload.get("iss") not in issuers:
            raise ValueError(f"unexpected issuer {payload.get('iss')!r}")
    if payload.get("typ") != expected_type:
        raise ValueError(f"expected {expected_type} token, got {payload.get('typ')!r}")
    audiences = allowed_audiences or [_AUD]
    # Legacy tokens (pre-audience) carry no aud; default them to the one surface
    # that remains. Drop this shim once JWT_SECRET has been rotated (Issue 2).
    if payload.get("aud", _AUD) not in audiences:
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


def issue_connector_access_token(user_id: str, resource: str, connection_jti: str | None = None,
                                 *, scopes: list[str] | None = None,
                                 oauth_client_id: str | None = None) -> tuple[str, int]:
    """Access token for MCP connector OAuth flows (Claude/ChatGPT connectors).

    Bound to the RFC 8707 resource indicator the client asked for:
    iss = the authorization-server issuer (PUBLIC_BASE_URL) and aud = the
    protected resource URL (https://api.zynd.ai/mcp). Hosts validate iss
    against the AS metadata and aud against the resource, so the legacy
    "zynd" audience is rejected there. Full-access scope for v1."""
    ttl = settings.access_token_ttl_seconds
    token = _encode(
        user_id, "access", ttl,
        iss=settings.public_base_url.rstrip("/"),
        aud=resource,
        scopes=["user"] if scopes is None else scopes,
        jti=connection_jti,
        oauth_client_id=oauth_client_id,
    )
    return token, ttl


def issue_refresh_token(user_id: str) -> str:
    return _encode(user_id, "refresh", settings.refresh_token_ttl_seconds)


def issue_rotating_refresh_token(user_id: str, *, bound: bool = False) -> tuple[str, str]:
    """(token, jti) — refresh tokens for public (PKCE/DCR/CIMD) clients are
    single-use and rotated on every redemption (Claude connector requirement)."""
    jti = secrets.token_urlsafe(24)
    token = _encode(user_id, "refresh", settings.refresh_token_ttl_seconds, jti=jti,
                    iss=settings.public_base_url.rstrip("/") if bound else None,
                    aud=settings.mcp_resource_url if bound else None)
    return token, jti


async def issue_client_token(pool, user_id: str, *, label: str, scopes: list[str]) -> tuple[str, str]:
    """Mint one assistant token without bumping token_version.

    Older personal tokens stay valid. Revoking this assistant sets
    mcp_clients.revoked_at for its jti. A full sign-out still bumps
    token_version, which kills every token that embedded the old ver.
    Returns (jwt, client_id).
    """
    import uuid

    from app.services.mcp_clients import normalize_scopes

    version = await pool.fetchval(
        "SELECT token_version FROM users WHERE id = $1", user_id,
    )
    if version is None:
        raise ValueError("unknown user")
    jti = str(uuid.uuid4())
    chosen = normalize_scopes(scopes)
    client_id = await pool.fetchval(
        """INSERT INTO mcp_clients (user_id, label, scopes, jti)
           VALUES ($1, $2, $3, $4::uuid) RETURNING id""",
        user_id, (label or "Assistant").strip()[:80] or "Assistant", chosen, jti,
    )
    token = _encode(
        user_id, "access", settings.mcp_token_ttl_seconds,
        ver=int(version), jti=jti, scopes=chosen,
    )
    return token, str(client_id)


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


def verify_access_meta(
    token: str,
    *,
    allowed_audiences: list[str] | None = None,
    allowed_issuers: list[str] | None = None,
) -> dict:
    """sub, iat, ver, jti, scopes, exp, iss, aud. `scopes` is None on legacy
    tokens (full access).

    Connector verification passes allowed_audiences/allowed_issuers so tokens
    bound to the MCP resource (aud) minted by the AS issuer (PUBLIC_BASE_URL)
    verify alongside legacy "zynd"-audience tokens."""
    payload = _decode_payload(
        token, "access",
        allowed_audiences=allowed_audiences,
        allowed_issuers=allowed_issuers,
    )
    ver = payload.get("ver")
    scopes = payload.get("scp")
    return {
        "sub": payload["sub"],
        "iat": int(payload.get("iat", 0)),
        "ver": int(ver) if ver is not None else None,
        "jti": payload.get("jti"),
        "scopes": list(scopes) if isinstance(scopes, list) else None,
        "exp": int(payload["exp"]) if payload.get("exp") else None,
        "iss": payload.get("iss"),
        "aud": payload.get("aud"),
        "oauth_client_id": payload.get("cid"),
    }


def verify_refresh_token(token: str) -> str:
    return _decode(token, "refresh")


def verify_refresh_claims(token: str) -> tuple[str, int]:
    """(user_id, iat) for a valid refresh token — for revocation-aware refresh."""
    return _decode_full(token, "refresh")


def verify_refresh_meta(token: str, *, bound: bool = False) -> tuple[str, int, str | None]:
    """(user_id, iat, jti) — jti is None for pre-rotation legacy refresh tokens."""
    payload = _decode_payload(token, "refresh",
        allowed_audiences=[settings.mcp_resource_url] if bound else None,
        allowed_issuers=[settings.public_base_url.rstrip("/")] if bound else None)
    return payload["sub"], int(payload.get("iat", 0)), payload.get("jti")
