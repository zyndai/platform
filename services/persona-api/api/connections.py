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

PROVIDERS = ["linkedin", "twitter", "google", "notion", "telegram"]


@router.get("/")
async def list_connections(user: dict = Depends(get_current_user)):
    """Return connection status for all providers."""
    user_conns = list_connected_providers(user["id"])
    
    # Map for easy lookup
    conn_map = {c["provider"]: c for c in user_conns}

    connections = {}
    for provider in ["linkedin", "twitter", "google", "notion"]:
        conn_info = conn_map.get(provider)
        connections[provider] = {
            "connected": provider in conn_map,
            "scopes": conn_info.get("scopes", "") if conn_info else "",
        }
        
    # Check manual telegram link database
    try:
        from api.telegram import get_mappings
        tg_mappings = get_mappings()
        connections["telegram"] = {
            "connected": any(v == user["id"] for v in tg_mappings.values()),
            "scopes": ""
        }
    except:
        connections["telegram"] = {"connected": False, "scopes": ""}

    return {"connections": connections}


@router.delete("/{provider}")
async def disconnect(provider: str, user: dict = Depends(get_current_user)):
    """Remove stored API tokens for a provider (disconnect)."""
    if provider not in PROVIDERS:
        return {"error": f"Unknown provider: {provider}"}
        
    if provider == "telegram":
        from api.telegram import get_mappings, MAPPING_FILE
        import json
        mappings = get_mappings()
        mappings = {k: v for k, v in mappings.items() if v != user["id"]}
        with open(MAPPING_FILE, "w") as f:
            json.dump(mappings, f)
        return {"status": "disconnected", "provider": provider}
        
    delete_tokens(user_id=user["id"], provider=provider)
    return {"status": "disconnected", "provider": provider}
