"""Verify a Supabase (Google) access token server-side and return the user's email.

We delegate verification to Supabase's /auth/v1/user endpoint (no need for the JWT
signing secret): a valid token returns the user, an invalid one returns 401.
"""
import httpx

from app.config import settings


async def supabase_email(access_token: str) -> str | None:
    if not access_token or not (settings.supabase_url and settings.supabase_anon_key):
        return None
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": settings.supabase_anon_key,
            })
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    email = resp.json().get("email")
    return email.strip().lower() if email else None
