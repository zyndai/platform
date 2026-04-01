"""
Auth routes — verifies Supabase JWT tokens from the frontend.

The frontend handles the actual login via Supabase Auth JS SDK.
These routes let the backend validate & identify the user on each
request using the Supabase JWT in the Authorization header.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import create_client, Client

import config

router = APIRouter()


def _get_supabase() -> Client:
    """Return a Supabase admin client (service-role key)."""
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


async def get_current_user(request: Request) -> dict:
    """
    Dependency — extract and verify user from the Authorization header.
    Returns the user dict from Supabase Auth.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = auth_header.removeprefix("Bearer ").strip()
    sb = _get_supabase()

    try:
        user_response = sb.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "user_metadata": user_response.user.user_metadata,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {str(e)}")


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return the currently logged-in user."""
    return user
