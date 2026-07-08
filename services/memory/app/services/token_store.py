
import json
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client

from app.config import settings

TABLE = "api_tokens"

_supabase_client: Client | None = None


def _sb() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def save_tokens(user_id: str, provider: str, tokens: dict) -> None:
    sb = _sb()
    expires_at = None
    if "expires_in" in tokens:
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
    sb = _sb()
    result = (
        sb.table(TABLE)
        .select("access_token, refresh_token, expires_at, scopes, raw_data")
        .eq("user_id", user_id)
        .eq("provider", provider)
        .maybe_single()
        .execute()
    )
    if not result or not hasattr(result, "data") or not result.data:
        return None
    row = result.data
    return {
        "access_token": row["access_token"],
        "refresh_token": row.get("refresh_token"),
        "expires_at": row.get("expires_at"),
        "scope": row.get("scopes", ""),
    }


def delete_tokens(user_id: str, provider: str) -> None:
    sb = _sb()
    sb.table(TABLE).delete().eq("user_id", user_id).eq("provider", provider).execute()


def list_connected_providers(user_id: str) -> list[dict]:
    sb = _sb()
    result = (
        sb.table(TABLE)
        .select("provider, scopes")
        .eq("user_id", user_id)
        .execute()
    )
    return result.data or []
