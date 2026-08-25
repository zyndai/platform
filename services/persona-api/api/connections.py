"""
Connections routes — list and manage OAuth API connections.

Reads from the `api_tokens` table to check which platforms
have stored API tokens (i.e. the user completed the custom
OAuth flow for that provider).
"""

import logging

from fastapi import APIRouter, Depends
from api.auth import get_current_user
from services.token_store import list_connected_providers, delete_tokens
from services import telegram_store
import config

logger = logging.getLogger(__name__)

router = APIRouter()

PROVIDERS = ["linkedin", "google", "notion", "github", "telegram"]

# Providers whose OAuth callback captures a username into api_tokens.raw_data
# (see api/oauth_routes._identity). Surfaced so the Accounts page can show
# "Connected as @handle".
USERNAME_PROVIDERS = {"github"}


@router.get("/")
async def list_connections(user: dict = Depends(get_current_user)):
    """Return connection status for all providers."""
    user_conns = list_connected_providers(user["id"])
    
    # Map for easy lookup
    conn_map = {c["provider"]: c for c in user_conns}

    connections = {}
    for provider in ["linkedin", "google", "notion", "github"]:
        conn_info = conn_map.get(provider)
        raw = (conn_info.get("raw_data") or {}) if conn_info else {}
        connections[provider] = {
            "connected": provider in conn_map,
            "scopes": conn_info.get("scopes", "") if conn_info else "",
            "username": raw.get("username") if provider in USERNAME_PROVIDERS else None,
        }
        
    # Telegram link lives in Supabase (telegram_links), written by the
    # /start webhook handshake — not in api_tokens. Connected iff this
    # user has a linked chat_id.
    try:
        connections["telegram"] = {
            "connected": telegram_store.get_chat_id_for_user(user["id"]) is not None,
            "scopes": "",
        }
    except Exception as e:
        logger.warning(f"[connections] telegram status check failed: {e}")
        connections["telegram"] = {"connected": False, "scopes": ""}

    return {"connections": connections}


@router.delete("/{provider}")
async def disconnect(provider: str, user: dict = Depends(get_current_user)):
    """Remove stored API tokens for a provider (disconnect)."""
    if provider not in PROVIDERS:
        return {"error": f"Unknown provider: {provider}"}
        
    if provider == "telegram":
        chat_id = telegram_store.get_chat_id_for_user(user["id"])
        if chat_id:
            telegram_store.unlink_chat(chat_id)
        return {"status": "disconnected", "provider": provider}
        
    delete_tokens(user_id=user["id"], provider=provider)
    return {"status": "disconnected", "provider": provider}


@router.delete("/{provider}/data")
async def delete_provider_data(provider: str, user: dict = Depends(get_current_user)):
    """Delete stored data for a provider while keeping the user's account.

    Removes OAuth tokens and, where applicable, stored provider content
    (e.g. the scraped LinkedIn profile). This is the granular "delete my
    <provider> data" compliance action, distinct from a full disconnect."""
    if provider not in PROVIDERS:
        return {"error": f"Unknown provider: {provider}"}

    if provider == "telegram":
        chat_id = telegram_store.get_chat_id_for_user(user["id"])
        if chat_id:
            telegram_store.unlink_chat(chat_id)
        return {"status": "deleted", "provider": provider}

    delete_tokens(user_id=user["id"], provider=provider)

    if provider == "linkedin":
        config.get_supabase().table("linkedin_profiles").delete().eq("user_id", user["id"]).execute()

    return {"status": "deleted", "provider": provider}
