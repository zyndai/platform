"""
Connections routes — list and manage OAuth API connections.

Reads from the `api_tokens` table to check which platforms
have stored API tokens (i.e. the user completed the custom
OAuth flow for that provider).
"""

from fastapi import APIRouter, Depends
from api.auth import get_current_user
from services.token_store import list_connected_providers, delete_tokens

router = APIRouter()

PROVIDERS = ["linkedin", "twitter", "google", "notion"]


@router.get("/")
async def list_connections(user: dict = Depends(get_current_user)):
    """Return connection status for all providers."""
    user_conns = list_connected_providers(user["id"])
    
    # Map for easy lookup
    conn_map = {c["provider"]: c for c in user_conns}

    connections = {}
    for provider in PROVIDERS:
        conn_info = conn_map.get(provider)
        connections[provider] = {
            "connected": provider in conn_map,
            "scopes": conn_info.get("scopes", "") if conn_info else "",
        }

    return {"connections": connections}


@router.delete("/{provider}")
async def disconnect(provider: str, user: dict = Depends(get_current_user)):
    """Remove stored API tokens for a provider (disconnect)."""
    if provider not in PROVIDERS:
        return {"error": f"Unknown provider: {provider}"}
    delete_tokens(user_id=user["id"], provider=provider)
    return {"status": "disconnected", "provider": provider}
