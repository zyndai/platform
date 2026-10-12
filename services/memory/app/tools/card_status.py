"""Authenticated owner card status bridge; no direct cards database access."""
import httpx

from app.config import settings


async def get_owner_status(pool, uid: str) -> dict:
    if not settings.feature_s10_home:
        return {"ok": False, "error": "Owner home is not enabled"}
    try:
        email = await pool.fetchval("SELECT email FROM users WHERE id = $1::uuid", uid)
    except Exception:
        return {"ok": False, "error": "Card connection unavailable"}
    if not email or not settings.memory_service_token:
        return {"ok": False, "error": "Card connection unavailable"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.cards_api_url.rstrip("/") + "/internal/owner-status",
                                         headers={"Authorization": "Bearer " + settings.memory_service_token},
                                         json={"email": email})
            response.raise_for_status()
            data = response.json()
        return {"ok": True, "data": data, "next_actions": (data or {}).get("completeness", {}).get("actions", [])}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "error": "Owner card status temporarily unavailable"}
