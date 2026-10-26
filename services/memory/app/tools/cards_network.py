"""Authenticated MCP client for the Cards-native social graph."""

from __future__ import annotations

from uuid import UUID

import httpx

from app.config import settings


async def _canonical(pool, uid: str) -> str:
    row = await pool.fetchrow("SELECT supabase_user_id FROM users WHERE id = $1", uid)
    if not row or not row["supabase_user_id"]:
        raise ValueError("Sign in with your shared Zynd account before using Cards networking")
    return str(UUID(str(row["supabase_user_id"])))


async def _call(pool, uid: str, method: str, path: str, **kwargs) -> dict:
    try:
        canonical = await _canonical(pool, uid)
    except ValueError:
        return {"ok": False, "error": "Sign in with your shared Zynd account before using Cards networking"}
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
        return {"ok": False, "status": response.status_code,
                "error": (data.get("detail") if isinstance(data, dict) else None) or "Cards network request failed"}
    return {"ok": True, **(data if isinstance(data, dict) else {"data": data})}


async def _call_with_search(pool, uid: str, method: str, path: str, body: dict, from_search: dict | None) -> dict:
    """A request that may say which search it came from. That is only for the funnel, so an older
    Cards that rejects the field (422) must never cost the user the action: send it again without."""
    if not from_search:
        return await _call(pool, uid, method, path, json=body)
    result = await _call(pool, uid, method, path, json={**body, "from_search": from_search})
    if not result.get("ok") and result.get("status") == 422:
        return await _call(pool, uid, method, path, json=body)
    return result


async def connections(pool, uid: str) -> dict:
    return await _call(pool, uid, "GET", "/connections")


async def request_connection(pool, uid: str, target_handle: str, message: str = "",
                             from_search: dict | None = None) -> dict:
    return await _call_with_search(
        pool, uid, "POST", "/connections", {"target_handle": target_handle, "message": message or None}, from_search)


async def create_invite(pool, uid: str, linkedin_url: str, name: str, headline: str, message: str = "",
                        from_search: dict | None = None) -> dict:
    return await _call_with_search(pool, uid, "POST", "/invites", {
        "linkedin_url": linkedin_url, "name": name, "headline": headline, "message": message or None}, from_search)


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
    return await _call(pool, uid, "GET", f"/groups/{group_id}/people", params={"query": query})


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


async def group_search(pool, uid: str, group_id: str, q: str, role: str, location: str, skills: str, limit: int,
                       topics: str = "", relax: bool = False) -> dict:
    params = {"q": q, "role": role, "location": location, "skills": skills, "limit": max(1, min(limit, 50))}
    if topics:
        params["topics"] = topics      # soft: scored, never required
    if relax:
        params["relax"] = "true"       # loosen the filters when too few members match
    return await _call(pool, uid, "GET", f"/groups/{group_id}/search", params=params)


async def preferences(pool, uid: str) -> dict:
    return await _call(pool, uid, "GET", "/preferences")


async def change_preference(pool, uid: str, kind: str, value: str, remove: bool = False) -> dict:
    return await _call(pool, uid, "POST", "/preferences/remove" if remove else "/preferences",
                       json={"kind": kind, "value": value})


async def saved_searches(pool, uid: str) -> dict:
    return await _call(pool, uid, "GET", "/saved-searches")


async def add_saved_search(pool, uid: str, q: str, role: str, location: str, skills: str, label: str) -> dict:
    return await _call(pool, uid, "POST", "/saved-searches", json={
        "q": q, "role": role, "location": location, "skills": skills, "label": label})


async def remove_saved_search(pool, uid: str, search_id: str) -> dict:
    return await _call(pool, uid, "DELETE", f"/saved-searches/{search_id}")


async def report_card(pool, uid: str, handle: str, reason: str, details: str) -> dict:
    return await _call(pool, uid, "POST", f"/cards/{handle}/report", json={"reason": reason, "details": details})


async def block_card(pool, uid: str, handle: str) -> dict:
    return await _call(pool, uid, "POST", f"/cards/{handle}/block")


async def brief(pool, uid: str, connection_id: str) -> dict:
    return await _call(pool, uid, "GET", f"/connections/{connection_id}/brief")
