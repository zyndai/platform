"""Per-user token revocation (sign-out / disconnect).

ZYND tokens are stateless JWTs, so we can't revoke an individual token. There are
two mechanisms, keyed on the token type:

- Long-lived personal tokens embed `ver` (the user's `token_version`). Minting a
  new one bumps the counter, instantly killing every older personal token.
- Short-lived OAuth access/refresh tokens (no `ver`) are governed by a
  `tokens_revoked_at` watermark: sign-out sets it to now(), and every auth path
  rejects any token issued at or before it.

Sign-out does both, so it kills access + refresh + MCP tokens at once and forces
a fresh sign-in — without affecting any other user.
"""
import asyncpg


async def revoke_user_tokens(pool: asyncpg.Pool, user_id: str) -> None:
    """Sign the user out everywhere: invalidate every token issued up to now."""
    await pool.execute(
        "UPDATE users SET tokens_revoked_at = now(), token_version = token_version + 1 WHERE id = $1",
        user_id,
    )


async def tokens_revoked(pool: asyncpg.Pool, user_id: str, issued_at: int) -> bool:
    """True if the user signed out at or after this token was issued.

    Compares the token's `iat` (whole seconds) against the watermark. The `<=`
    means a token minted in the same second as sign-out is revoked too (the
    rare re-login-in-the-same-second false positive is an acceptable one extra
    re-login). This only governs short-lived OAuth tokens now.
    """
    revoked_at = await pool.fetchval(
        "SELECT tokens_revoked_at FROM users WHERE id = $1", user_id)
    if revoked_at is None:
        return False
    return issued_at <= int(revoked_at.timestamp())


async def token_rejected(pool: asyncpg.Pool, user_id: str, issued_at: int,
                         ver: int | None = None) -> bool:
    """True if this token should be rejected. Version-gated personal tokens (ver
    is not None) are rejected when their version is no longer current; short-lived
    tokens fall back to the revocation watermark."""
    if ver is not None:
        current = await pool.fetchval(
            "SELECT token_version FROM users WHERE id = $1", user_id)
        return current is None or int(current) != ver
    return await tokens_revoked(pool, user_id, issued_at)
