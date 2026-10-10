"""User identity resolution for token-mint paths.

`supabase_user_id` (`sub`) is the authoritative identity key once present; email
is the legacy/secondary key used only for rows that have no `sub` yet (xmfj cards
users before the aafo cutover). A verified `sub` is resolved first, and an existing
`sub` link is never overwritten by a different identity.
"""
import logging

import asyncpg

logger = logging.getLogger("zynd.users")

_SYNTHETIC_EMAIL_DOMAIN = "conflict.zynd.local"


async def resolve_user(
    pool: asyncpg.Pool,
    email: str,
    display_name: str,
    sub: str | None,
) -> str:
    """Resolve (or create) the memory user for a verified Supabase identity.

    Returns the memory-layer user id. Keying order:
      1. sub-first: a row already linked to this Supabase user id wins.
      2. email: a row with this email and no (or the same) sub is linked/returned.
      3. conflict: an email already linked to a *different* sub is a distinct
         identity — a separate memory user is created (never overwritten).

    Never clobbers an existing non-null `supabase_user_id`.
    """
    email = (email or "").strip().lower()
    sub = (sub or "").strip() or None
    display_name = (display_name or "").strip() or (email.split("@", 1)[0] if email else "")

    if sub:
        row = await pool.fetchrow("SELECT id FROM users WHERE supabase_user_id = $1", sub)
        if row:
            return str(row["id"])

    row = await pool.fetchrow(
        "SELECT id, supabase_user_id FROM users WHERE lower(email) = lower($1)", email)
    if row:
        existing_sub = row["supabase_user_id"]
        if sub is not None and existing_sub is not None and existing_sub != sub:
            logger.warning(
                "email %s already linked to sub %s; minting a separate memory user for sub %s",
                email, existing_sub, sub)
        else:
            if sub is not None and existing_sub is None:
                await pool.execute(
                    "UPDATE users SET supabase_user_id = $2, display_name = $3 WHERE id = $1",
                    row["id"], sub, display_name)
            else:
                await pool.execute(
                    "UPDATE users SET display_name = $2 WHERE id = $1", row["id"], display_name)
            return str(row["id"])

    insert_email = email
    if sub:
        taken_sub = await pool.fetchval(
            "SELECT supabase_user_id FROM users WHERE lower(email) = lower($1)", email)
        if taken_sub is not None and taken_sub != sub:
            insert_email = f"{sub}@{_SYNTHETIC_EMAIL_DOMAIN}"

    return str(await pool.fetchval(
        """INSERT INTO users (email, display_name, supabase_user_id)
           VALUES ($1, $2, $3) RETURNING id""",
        insert_email, display_name, sub))
