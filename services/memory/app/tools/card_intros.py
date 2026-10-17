"""MCP bridge for verified-card introductions, keyed by account UUID."""

import uuid
from uuid import UUID
import httpx
from app.config import settings


async def _canonical_uid(pool, uid: str) -> str | None:
    try:
        linked = await pool.fetchval(
            "SELECT supabase_user_id FROM users WHERE id = $1::uuid", uid
        )
        return str(UUID(str(linked))) if linked else None
    except (ValueError, TypeError):
        return None


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + settings.memory_service_token}


def _enabled() -> str | None:
    if not settings.feature_s12_intros or not settings.feature_s12_mcp_actions:
        return "Verified-card MCP introductions are not enabled"
    if not settings.s12_identity_issuer or not settings.memory_service_token:
        return "Shared identity is not configured"
    return None


async def request_intro(
    pool,
    uid: str,
    handle: str,
    why: str,
    asks: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create one verified-card intro through the Cards service bridge."""
    if error := _enabled():
        return {"ok": False, "error": error}
    canonical = await _canonical_uid(pool, uid)
    if not canonical:
        return {"ok": False, "error": "Your shared account identity is not linked"}
    try:
        key = str(UUID(idempotency_key)) if idempotency_key else str(uuid.uuid4())
    except (ValueError, TypeError):
        return {"ok": False, "error": "idempotency_key must be a UUID"}
    clean_asks = sorted(set(asks or ["message"]))
    if not clean_asks or any(item not in {"message", "meeting"} for item in clean_asks):
        return {"ok": False, "error": "asks must contain message and/or meeting"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                settings.cards_api_url.rstrip("/") + "/internal/mcp-intro",
                headers=_headers(),
                json={
                    "handle": (handle or "").strip().lstrip("@"),
                    "requester_uid": canonical,
                    "why": why,
                    "asks": clean_asks,
                    "idempotency_key": key,
                },
            )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            return {"ok": False, "error": detail or "Could not send the verified-card intro"}
        return {"ok": True, "intro": response.json()}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"Intro service temporarily unavailable: {exc}"}


async def list_intros(pool, uid: str, outgoing: bool = False) -> dict:
    """Read the authenticated user's sent or received verified-card intros."""
    if error := _enabled():
        return {"ok": False, "error": error}
    canonical = await _canonical_uid(pool, uid)
    if not canonical:
        return {"ok": False, "error": "Your shared account identity is not linked"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                settings.cards_api_url.rstrip("/") + "/internal/mcp-intros",
                headers=_headers(),
                json={
                    "zynd_uid": canonical,
                    "issuer": settings.s12_identity_issuer,
                    "outgoing": bool(outgoing),
                },
            )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            return {"ok": False, "error": detail or "Could not read verified-card intros"}
        return {"ok": True, "intros": response.json().get("intros", [])}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"Intro service temporarily unavailable: {exc}"}


async def get_owner_intros(pool, uid: str) -> dict:
    """Read-only owner inbox bridge, retained for the cards:read tool."""
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
