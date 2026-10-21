"""Read-only S12 owner bridge, keyed by the authenticated account UUID."""

from uuid import UUID
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def _failure(code: str, message: str, *, retryable: bool = False) -> dict:
    return {"ok": False, "error": message, "code": code, "retryable": retryable}


async def get_owner_intros(pool, uid: str) -> dict:
    if not settings.feature_s12_intros:
        return _failure("not_enabled", "Introductions are not enabled")
    if not settings.s12_identity_issuer or not settings.memory_service_token:
        return _failure("not_configured", "Shared identity is not configured")
    try:
        linked = await pool.fetchval(
            "SELECT supabase_user_id FROM users WHERE id = $1::uuid", uid
        )
    except Exception:
        logger.warning("owner intros identity lookup failed", exc_info=True)
        return _failure("identity_unavailable", "Shared identity temporarily unavailable", retryable=True)
    try:
        canonical = str(UUID(str(linked)))
    except (ValueError, TypeError):
        return _failure("identity_not_linked", "Sign in with your shared Zynd account before reading introductions")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                settings.cards_api_url.rstrip("/") + "/internal/owner-intros",
                headers={"Authorization": "Bearer " + settings.memory_service_token},
                json={"zynd_uid": canonical, "issuer": settings.s12_identity_issuer},
            )
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("intros"), list):
            raise ValueError("invalid owner-intros response")
        return {
            "ok": True,
            "data": result["intros"],
            "next_actions": ["Review and respond in the Cards or Persona intro inbox"],
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("owner intros upstream rejected request status=%s", status)
        if status == 409:
            return _failure("identity_not_ready", "Shared identity linkage is not ready")
        if status in (401, 403, 404):
            return _failure("service_configuration", "Owner introductions are unavailable; service configuration needs review")
        return _failure("upstream_unavailable", "Owner introductions are temporarily unavailable", retryable=True)
    except httpx.TimeoutException:
        logger.warning("owner intros upstream timed out")
        return _failure("upstream_timeout", "Owner introductions timed out; try again", retryable=True)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        logger.warning("owner intros upstream response unavailable or invalid")
        return _failure("upstream_unavailable", "Owner introductions are temporarily unavailable", retryable=True)
