"""
Token Store — manages scoped OAuth API tokens in the `api_tokens` table.

These are the platform API access tokens (LinkedIn, Twitter, Google)
needed to call their APIs on behalf of the user. They are separate
from Supabase auth tokens which only handle login identity.

The table schema is in db/schema.sql.
"""

import json
from datetime import datetime, timezone
from supabase import create_client, Client
import config

TABLE = "api_tokens"


def _sb() -> Client:
    """Service-role client — bypasses RLS for backend operations."""
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def save_tokens(
    user_id: str,
    provider: str,
    tokens: dict,
) -> None:
    """
    Upsert API tokens for a user + provider.

    Args:
        user_id: Supabase user ID
        provider: 'linkedin', 'twitter', or 'google'
        tokens: dict with at least 'access_token', optionally
                'refresh_token', 'expires_in', 'scope', etc.
    """
    sb = _sb()

    # Calculate expiry if provided
    expires_at = None
    if "expires_in" in tokens:
        expires_at = datetime.now(timezone.utc).isoformat()
        from datetime import timedelta
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
        ).isoformat()

    sb.table(TABLE).upsert(
        {
            "user_id": user_id,
            "provider": provider,
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": expires_at,
            "scopes": tokens.get("scope", ""),
            "raw_data": json.dumps(tokens),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,provider",
    ).execute()


def get_tokens(user_id: str, provider: str) -> dict | None:
    """
    Retrieve API tokens for a user + provider.

    Returns:
        dict with 'access_token', 'refresh_token', etc. or None if not found.
    """
    sb = _sb()
    result = (
        sb.table(TABLE)
        .select("access_token, refresh_token, expires_at, scopes, raw_data")
        .eq("user_id", user_id)
        .eq("provider", provider)
        .maybe_single()
        .execute()
    )

    if not result or not hasattr(result, 'data') or not result.data:
        return None

    row = result.data
    return {
        "access_token": row["access_token"],
        "refresh_token": row.get("refresh_token"),
        "expires_at": row.get("expires_at"),
        "scope": row.get("scopes", ""),
    }


def delete_tokens(user_id: str, provider: str) -> None:
    """Delete API tokens for a user + provider (disconnect)."""
    sb = _sb()
    sb.table(TABLE).delete().eq("user_id", user_id).eq("provider", provider).execute()


def list_connected_providers(user_id: str) -> list[dict]:
    """Return info for all platform providers that have stored API tokens."""
    sb = _sb()
    result = (
        sb.table(TABLE)
        .select("provider, scopes")
        .eq("user_id", user_id)
        .execute()
    )
    return result.data or []
