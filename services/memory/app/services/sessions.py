"""Per-user token revocation (sign-out / disconnect).

ZYND tokens are stateless JWTs, so we can't revoke an individual token. Instead each
user has a `tokens_revoked_at` watermark: sign-out sets it to now(), and every auth path
rejects any token issued before it. This kills the user's current access + refresh + MCP
tokens at once and forces a fresh sign-in — without affecting any other user.
"""
import asyncpg


async def revoke_user_tokens(pool: asyncpg.Pool, user_id: str) -> None:
    """Sign the user out everywhere: invalidate every token issued up to now."""
    await pool.execute("UPDATE users SET tokens_revoked_at = now() WHERE id = $1", user_id)


async def tokens_revoked(pool: asyncpg.Pool, user_id: str, issued_at: int) -> bool:
    """True if the user signed out after this token was issued.

    Compares the token's `iat` (whole seconds) against the watermark floored to the
    second, so a token minted in the *same* second as a fresh re-login is NOT falsely
    revoked (1s grace); tokens from any earlier second are rejected.
    """
    revoked_at = await pool.fetchval(
        "SELECT tokens_revoked_at FROM users WHERE id = $1", user_id)
    if revoked_at is None:
        return False
    return issued_at < int(revoked_at.timestamp())
