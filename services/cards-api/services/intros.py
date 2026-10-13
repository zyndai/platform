"""HTTP-only Persona/Memory integration; S12 never infers identity from email."""

import asyncio
from uuid import UUID
import httpx
from fastapi import HTTPException
import config


def enabled():
    if not config.FEATURE_S12_INTROS or config.SUPABASE_DB_SCHEMA != "cards":
        raise HTTPException(404, "Intros are not enabled")
    if (
        not config.AAFO_ISSUER
        or config.AAFO_ISSUER != config.SUPABASE_URL.rstrip("/") + "/auth/v1"
    ):
        raise HTTPException(503, "Shared account issuer is not configured")


async def persona(path: str, method="GET", body=None) -> dict:
    if not config.CARDS_INTRO_SERVICE_TOKEN:
        raise HTTPException(503, "Intro service is not configured")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.request(
                method,
                config.PERSONA_API_URL.rstrip("/") + "/api/intros/internal" + path,
                headers={"Authorization": "Bearer " + config.CARDS_INTRO_SERVICE_TOKEN},
                json=body,
            )
        if response.status_code >= 400:
            detail = response.json().get("detail")
            message = (
                detail
                if isinstance(detail, str)
                else "Check your intro details and try again"
            )
            raise HTTPException(
                response.status_code
                if response.status_code in (403, 409, 422, 429)
                else 503,
                message,
            )
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            503, "Intro service temporarily unavailable; retry this request"
        ) from exc


async def memory_identity(uid: str):
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(503, "Identity service is not configured")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                config.MEMORY_LAYER_URL.rstrip("/") + "/v1/service/identity/" + uid,
                headers={"Authorization": "Bearer " + config.MEMORY_SERVICE_TOKEN},
            )
        data = response.json()
        if (
            response.status_code != 200
            or data.get("zynd_uid") != uid
            or data.get("issuer") != config.AAFO_ISSUER
        ):
            raise HTTPException(
                409 if response.status_code in (200, 404, 409) else 503,
                "Shared identity linkage is not ready",
            )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Identity service temporarily unavailable") from exc


def card_row(handle: str) -> dict:
    rows = (
        config.get_supabase()
        .table("agent_profile_cards")
        .select("id,handle,status,owner_email,owner_user_id")
        .eq("handle", handle)
        .limit(1)
        .execute()
        .data
        or []
    )
    if (
        not rows
        or rows[0]["status"] != "published"
        or not rows[0].get("owner_email")
        or not rows[0].get("owner_user_id")
    ):
        raise HTTPException(404, "This card is not available for introductions")
    try:
        UUID(rows[0]["owner_user_id"])
    except ValueError as exc:
        raise HTTPException(409, "Card identity linkage is not ready") from exc
    return rows[0]


async def eligibility(handle: str) -> dict:
    row = await asyncio.to_thread(card_row, handle)
    active = await persona("/agents/" + row["owner_user_id"])
    if not active.get("active") or active.get("issuer") != config.AAFO_ISSUER:
        raise HTTPException(409, "An active linked Persona is required")
    await memory_identity(row["owner_user_id"])
    return {"available": True, "agent_id": active["agent_id"]}


async def sync(rows: list[dict]):
    # Retries repair projection gaps after a Persona success/Cards failure.
    for row in rows:
        await asyncio.to_thread(
            lambda row=row: (
                config.get_supabase()
                .rpc(
                    "s12_sync_intro",
                    {"p_intro": row, "p_track": bool(config.FEATURE_S04_EVENTS)},
                )
                .execute()
            )
        )


def public_record(row: dict) -> dict:
    fields = (
        "id",
        "handle",
        "requester_uid",
        "owner_uid",
        "requester_name",
        "owner_name",
        "why",
        "asks",
        "permissions",
        "status",
        "thread_id",
        "meeting_task_id",
        "created_at",
        "decided_at",
    )
    result = {key: row.get(key) for key in fields}
    result["conversation_url"] = (
        config.PERSONA_SITE_URL.rstrip("/")
        + "/dashboard/messages?thread="
        + row["thread_id"]
    )
    return result


def require_scope(rows: list[dict], uid: str, outgoing: bool = False):
    field = "requester_uid" if outgoing else "owner_uid"
    if any(row.get(field) != uid for row in rows):
        raise HTTPException(503, "Could not verify intro ownership")
