"""Authenticated MCP client for the Cards-native social graph."""

from __future__ import annotations

import httpx

from app.config import settings


async def _canonical(pool, uid: str) -> str:
    row = await pool.fetchrow("SELECT supabase_user_id FROM users WHERE id = $1", uid)
    value = row["supabase_user_id"] if row and row["supabase_user_id"] else uid
    return str(value)


async def _call(pool, uid: str, method: str, path: str, **kwargs) -> dict:
    canonical = await _canonical(pool, uid)
    headers = {
        "Authorization": "Bearer " + settings.memory_service_token,
        "X-Zynd-User": canonical,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                settings.cards_api_url.rstrip("/") + "/cards/network" + path,
                headers=headers,
                **kwargs,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"Cards network unavailable: {exc}"}
    if response.status_code >= 400:
        return {"ok": False, "error": data.get("detail") or "Cards network request failed"}
    return {"ok": True, **(data if isinstance(data, dict) else {"data": data})}


async def connections(pool, uid: str) -> dict:
    return await _call(pool, uid, "GET", "/connections")


async def request_connection(pool, uid: str, target_handle: str, message: str = "") -> dict:
    return await _call(pool, uid, "POST", "/connections", json={"target_handle": target_handle, "message": message or None})


async def respond_connection(pool, uid: str, connection_id: str, action: str) -> dict:
    return await _call(pool, uid, "POST", f"/connections/{connection_id}/respond", json={"action": action})


async def read_dm(pool, uid: str, connection_id: str, limit: int = 100) -> dict:
    return await _call(pool, uid, "GET", f"/connections/{connection_id}/messages?limit={max(1, min(limit, 500))}")


async def send_dm(pool, uid: str, connection_id: str, content: str) -> dict:
    return await _call(pool, uid, "POST", f"/connections/{connection_id}/messages", json={"content": content})


async def groups(pool, uid: str) -> dict:
    return await _call(pool, uid, "GET", "/groups")


async def create_group(pool, uid: str, name: str, description: str = "", visibility: str = "private") -> dict:
    return await _call(pool, uid, "POST", "/groups", json={"name": name, "description": description or None, "visibility": visibility})


async def group_people(pool, uid: str, group_id: str, query: str = "") -> dict:
    return await _call(pool, uid, "GET", f"/groups/{group_id}/people?query={query}")


async def invite_group(pool, uid: str, group_id: str, target_handle: str, message: str = "") -> dict:
    return await _call(pool, uid, "POST", f"/groups/{group_id}/invitations", json={"target_handle": target_handle, "message": message or None})


async def incoming_invites(pool, uid: str) -> dict:
    return await _call(pool, uid, "GET", "/group-invitations")


async def respond_invite(pool, uid: str, invitation_id: str, decision: str) -> dict:
    return await _call(pool, uid, "POST", f"/group-invitations/{invitation_id}/respond", json={"decision": decision})


async def group_messages(pool, uid: str, group_id: str, limit: int = 100) -> dict:
    return await _call(pool, uid, "GET", f"/groups/{group_id}/messages?limit={max(1, min(limit, 500))}")


async def send_group_message(pool, uid: str, group_id: str, content: str) -> dict:
    return await _call(pool, uid, "POST", f"/groups/{group_id}/messages", json={"content": content})
