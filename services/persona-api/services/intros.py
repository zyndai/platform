"""Persona owns intro decisions; SQL serializes decisions and retries."""

from fastapi import HTTPException
from postgrest.exceptions import APIError
import config

ERRORS = {
    "persona_required": (
        409,
        "Both people need an active Persona before requesting an intro",
    ),
    "connection_exists": (409, "A connection already exists; continue in Persona"),
    "idempotency_conflict": (
        409,
        "This submission key was already used for a different request",
    ),
    "denied": (403, "This owner is not accepting this request"),
    "rate_limited": (429, "Daily intro limit reached; try another day"),
}


def operation(name: str, args: dict) -> dict:
    try:
        result = config.get_supabase().rpc(name, args).execute().data
    except APIError as exc:
        code = str(exc.code)
        raise HTTPException(
            {"42501": 403, "40001": 409, "23505": 409, "22023": 422}.get(code, 503),
            "Intro operation refused"
            if code in {"42501", "40001", "23505", "22023"}
            else "Intro service unavailable",
        ) from exc
    if not isinstance(result, dict):
        raise HTTPException(503, "Intro service unavailable")
    if result.get("error"):
        code, message = ERRORS.get(result["error"], (503, "Intro service unavailable"))
        raise HTTPException(code, message)
    if result.get("id") and result.get("thread_id"):
        result = with_acceptance([result])[0]
    return result


def respond(intro_id: str, actor: str, body) -> dict:
    return operation(
        "s12_respond_intro",
        {
            "p_id": intro_id,
            "p_actor": actor,
            "p_action": body.action,
            "p_allow_meetings": body.allow_meetings,
            "p_start": body.start_time.isoformat() if body.start_time else None,
            "p_end": body.end_time.isoformat() if body.end_time else None,
        },
    )


def list_for(uid: str, outgoing: bool = False, offset: int = 0) -> list[dict]:
    rows = (
        config.get_supabase()
        .table("persona_intro_requests")
        .select("*")
        .eq("requester_uid" if outgoing else "owner_uid", uid)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + 99)
        .execute()
        .data
        or []
    )
    return with_acceptance(rows)


def pending_count(uid: str) -> int:
    result = (
        config.get_supabase()
        .table("persona_intro_requests")
        .select("id", count="exact", head=True)
        .eq("owner_uid", uid)
        .eq("status", "pending")
        .execute()
    )
    return result.count or 0


def with_acceptance(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    accepted = (
        config.get_supabase()
        .table("persona_intro_audit")
        .select("intro_id,created_at")
        .in_("intro_id", [row["id"] for row in rows])
        .eq("action", "accepted")
        .execute()
        .data
        or []
    )
    times = {event["intro_id"]: event["created_at"] for event in accepted}
    threads = (
        config.get_supabase()
        .table("dm_threads")
        .select("id,permissions")
        .in_("id", [row["thread_id"] for row in rows])
        .execute()
        .data
        or []
    )
    permissions = {thread["id"]: thread["permissions"] for thread in threads}
    return [
        {
            **row,
            "accepted_at": times.get(row["id"]),
            "permissions": permissions.get(row["thread_id"], row["permissions"]),
        }
        for row in rows
    ]
