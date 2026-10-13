"""Read-only S12 owner bridge, keyed by the authenticated account UUID."""

from uuid import UUID
import httpx
from app.config import settings


async def get_owner_intros(pool, uid: str) -> dict:
    if not settings.feature_s12_intros:
        return {"ok": False, "error": "Introductions are not enabled"}
    if not settings.s12_identity_issuer or not settings.memory_service_token:
        return {"ok": False, "error": "Shared identity is not configured"}
    try:
        linked = await pool.fetchval(
            "SELECT supabase_user_id FROM users WHERE id = $1::uuid", uid
        )
    except Exception:
        return {"ok": False, "error": "Shared identity temporarily unavailable"}
    try:
        canonical = str(UUID(str(linked)))
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                settings.cards_api_url.rstrip("/") + "/internal/owner-intros",
                headers={"Authorization": "Bearer " + settings.memory_service_token},
                json={"zynd_uid": canonical, "issuer": settings.s12_identity_issuer},
            )
            response.raise_for_status()
            result = response.json()
        return {
            "ok": True,
            "data": result["intros"],
            "next_actions": ["Review and respond in the Cards or Persona intro inbox"],
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return {"ok": False, "error": "Owner introductions are temporarily unavailable"}
