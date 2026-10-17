"""Cards-native connections, direct messages, and groups.

Cards is the source of truth for this social graph. The service-role client is
used deliberately: browser callers authenticate with a shared Supabase session
and this module enforces every ownership, acceptance, and membership check
before writing the Cards schema.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException

import config


MAX_GROUP_MEMBERS = 50


def _sb():
    if config.SUPABASE_DB_SCHEMA != "cards":
        raise HTTPException(503, "Cards networking requires the shared cards schema")
    return config.get_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_key(first: str, second: str) -> str:
    return ":".join(sorted((str(UUID(first)), str(UUID(second)))))


def _card_payload(row: dict) -> dict:
    card = row.get("card") or {}
    identity = card.get("identity") or {}
    profile = card.get("profile") or {}
    return {
        "card_id": row.get("id"),
        "handle": row.get("handle"),
        "name": identity.get("name") or "Zynd member",
        "headline": identity.get("headline") or "",
        "avatar_url": identity.get("avatar_url") or profile.get("avatar_url"),
    }


def _card_for_user(user_id: str) -> dict:
    rows = (
        _sb()
        .table("agent_profile_cards")
        .select("id,handle,card,status,owner_user_id,owner_email")
        .eq("owner_user_id", user_id)
        .eq("status", "published")
        .not_.is_("owner_email", "null")
        .order("published_at", desc=True, nullsfirst=False)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(409, "You need a claimed, published Card before using Connections")
    return rows[0]


def _card_for_handle(handle: str) -> dict:
    rows = (
        _sb()
        .table("agent_profile_cards")
        .select("id,handle,card,status,owner_user_id,owner_email")
        .eq("handle", handle.strip().lstrip("@"))
        .eq("status", "published")
        .not_.is_("owner_email", "null")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or not rows[0].get("owner_user_id"):
        raise HTTPException(404, "That verified Card is not available")
    return rows[0]


def _connection_row(connection_id: str) -> dict:
    rows = _sb().table("connections").select("*").eq("id", connection_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(404, "Connection not found")
    return rows[0]


def _require_connection_party(row: dict, user_id: str) -> bool:
    if user_id not in {row.get("requester_user_id"), row.get("recipient_user_id")}:
        raise HTTPException(404, "Connection not found")
    return row.get("requester_user_id") == user_id


def _partner_card(row: dict, user_id: str) -> dict:
    partner_id = row["recipient_card_id"] if row["requester_user_id"] == user_id else row["requester_card_id"]
    cards = _sb().table("agent_profile_cards").select("id,handle,card").eq("id", partner_id).limit(1).execute().data or []
    return _card_payload(cards[0]) if cards else {"card_id": partner_id, "name": "Zynd member"}


def _serialize_connection(row: dict, user_id: str) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "incoming": row["recipient_user_id"] == user_id,
        "created_at": row.get("created_at"),
        "decided_at": row.get("decided_at"),
        "updated_at": row.get("updated_at"),
        "partner": _partner_card(row, user_id),
    }


def request_connection(user_id: str, target_handle: str, message: str | None = None) -> dict:
    requester = _card_for_user(user_id)
    recipient = _card_for_handle(target_handle)
    recipient_user_id = recipient["owner_user_id"]
    if recipient_user_id == user_id:
        raise HTTPException(422, "You cannot connect to your own Card")

    key = _connection_key(user_id, recipient_user_id)
    existing = _sb().table("connections").select("*").eq("connection_key", key).limit(1).execute().data or []
    if existing:
        return {"connection": _serialize_connection(existing[0], user_id), "existing": True}

    try:
        inserted = _sb().table("connections").insert({
            "connection_key": key,
            "requester_user_id": user_id,
            "requester_card_id": requester["id"],
            "recipient_user_id": recipient_user_id,
            "recipient_card_id": recipient["id"],
            "request_message": (message or "").strip()[:2000] or None,
            "status": "pending",
        }).execute()
    except Exception as exc:
        if getattr(exc, "code", None) == "23505" or "duplicate key" in str(exc).lower():
            existing = _sb().table("connections").select("*").eq("connection_key", key).limit(1).execute().data or []
            if existing:
                return {"connection": _serialize_connection(existing[0], user_id), "existing": True}
        raise
    if not inserted.data:
        raise HTTPException(500, "Could not create connection request")
    return {"connection": _serialize_connection(inserted.data[0], user_id), "existing": False}


def list_connections(user_id: str) -> dict:
    rows = (
        _sb().table("connections").select("*")
        .or_(f"requester_user_id.eq.{user_id},recipient_user_id.eq.{user_id}")
        .order("updated_at", desc=True)
        .execute().data or []
    )
    return {"connections": [_serialize_connection(row, user_id) for row in rows]}


def respond_connection(user_id: str, connection_id: str, action: str) -> dict:
    if action not in {"accept", "decline", "block", "revoke"}:
        raise HTTPException(400, "Invalid connection action")
    row = _connection_row(connection_id)
    is_requester = _require_connection_party(row, user_id)
    if action in {"accept", "decline"} and is_requester:
        raise HTTPException(403, "Only the receiving Card can decide this request")

    allowed = {
        "accept": {"pending"},
        "decline": {"pending"},
        "block": {"pending", "accepted"},
        "revoke": {"accepted"},
    }
    if row["status"] not in allowed[action]:
        raise HTTPException(409, f"Cannot {action} a connection in '{row['status']}' state")
    new_status = {"accept": "accepted", "decline": "declined", "block": "blocked", "revoke": "revoked"}[action]
    updated = _sb().table("connections").update({
        "status": new_status,
        "decided_at": _now(),
        "updated_at": _now(),
    }).eq("id", connection_id).eq("status", row["status"]).execute()
    if not updated.data:
        raise HTTPException(409, "Connection changed; reload before deciding")
    if new_status == "accepted":
        _sb().table("dm_threads").upsert({"connection_id": connection_id, "updated_at": _now()}, on_conflict="connection_id").execute()
    return {"connection": _serialize_connection(updated.data[0], user_id)}


def _accepted_connection(user_id: str, connection_id: str) -> dict:
    row = _connection_row(connection_id)
    _require_connection_party(row, user_id)
    if row.get("status") != "accepted":
        raise HTTPException(409, "Accept the connection before messaging")
    return row


def _thread_for_connection(connection_id: str) -> dict:
    rows = _sb().table("dm_threads").select("*").eq("connection_id", connection_id).limit(1).execute().data or []
    if not rows:
        created = _sb().table("dm_threads").insert({"connection_id": connection_id}).execute().data or []
        if not created:
            raise HTTPException(500, "Could not open the conversation")
        return created[0]
    return rows[0]


def list_messages(user_id: str, connection_id: str, limit: int = 100) -> dict:
    _accepted_connection(user_id, connection_id)
    thread = _thread_for_connection(connection_id)
    rows = (_sb().table("dm_messages").select("id,thread_id,sender_user_id,content,created_at")
            .eq("thread_id", thread["id"]).order("created_at").limit(max(1, min(limit, 500))).execute().data or [])
    return {"thread_id": thread["id"], "messages": rows}


def send_message(user_id: str, connection_id: str, content: str) -> dict:
    _accepted_connection(user_id, connection_id)
    text = content.strip()
    if not text:
        raise HTTPException(400, "Message cannot be empty")
    thread = _thread_for_connection(connection_id)
    inserted = _sb().table("dm_messages").insert({
        "thread_id": thread["id"],
        "sender_user_id": user_id,
        "content": text[:4000],
    }).execute()
    _sb().table("dm_threads").update({"updated_at": _now()}).eq("id", thread["id"]).execute()
    return {"message": (inserted.data or [None])[0]}


def _group(group_id: str) -> dict:
    rows = _sb().table("groups").select("*").eq("id", group_id).is_("archived_at", "null").limit(1).execute().data or []
    if not rows:
        raise HTTPException(404, "Group not found")
    return rows[0]


def _member(group_id: str, user_id: str) -> dict | None:
    rows = _sb().table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def _require_member(group_id: str, user_id: str) -> dict:
    member = _member(group_id, user_id)
    if not member:
        raise HTTPException(404, "Group not found")
    return member


def create_group(user_id: str, name: str, description: str | None, visibility: str) -> dict:
    _card_for_user(user_id)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(400, "Group name cannot be empty")
    if visibility not in {"private", "open"}:
        raise HTTPException(400, "visibility must be private or open")
    group = _sb().table("groups").insert({
        "name": clean_name[:80],
        "description": (description or "").strip()[:500] or None,
        "owner_user_id": user_id,
        "visibility": visibility,
    }).execute().data or []
    if not group:
        raise HTTPException(500, "Could not create group")
    _sb().table("group_members").insert({"group_id": group[0]["id"], "user_id": user_id, "role": "owner"}).execute()
    return {"group": group[0]}


def list_groups(user_id: str) -> dict:
    rows = _sb().table("group_members").select("group_id,role").eq("user_id", user_id).execute().data or []
    ids = [row["group_id"] for row in rows]
    if not ids:
        return {"groups": []}
    groups = _sb().table("groups").select("*").in_("id", ids).is_("archived_at", "null").order("updated_at", desc=True).execute().data or []
    role_by_id = {row["group_id"]: row["role"] for row in rows}
    return {"groups": [{**group, "my_role": role_by_id.get(group["id"], "member")} for group in groups]}


def list_members(user_id: str, group_id: str) -> dict:
    _require_member(group_id, user_id)
    rows = _sb().table("group_members").select("*").eq("group_id", group_id).order("joined_at").execute().data or []
    if not rows:
        return {"members": []}
    user_ids = [row["user_id"] for row in rows]
    cards = _sb().table("agent_profile_cards").select("id,owner_user_id,handle,card").in_("owner_user_id", user_ids).eq("status", "published").execute().data or []
    by_user = {row.get("owner_user_id"): _card_payload(row) for row in cards}
    return {"members": [{**row, "card": by_user.get(row["user_id"])} for row in rows]}


def _connected(user_id: str, target_user_id: str) -> bool:
    key = _connection_key(user_id, target_user_id)
    rows = _sb().table("connections").select("id").eq("connection_key", key).eq("status", "accepted").limit(1).execute().data or []
    return bool(rows)


def search_invitable(user_id: str, group_id: str, query: str) -> dict:
    manager = _require_member(group_id, user_id)
    if manager.get("role") != "owner":
        raise HTTPException(403, "Only the group owner can invite people")
    existing = _sb().table("group_members").select("user_id").eq("group_id", group_id).execute().data or []
    excluded = {row["user_id"] for row in existing}
    pattern = f"%{query.strip()}%"
    cards = (_sb().table("agent_profile_cards").select("id,owner_user_id,handle,card")
             .eq("status", "published").not_.is_("owner_user_id", "null")
             .limit(100).execute().data or [])
    results = []
    for card in cards:
        target = card.get("owner_user_id")
        if not target or target in excluded or target == user_id or not _connected(user_id, target):
            continue
        payload = _card_payload(card)
        haystack = f"{payload.get('handle') or ''} {payload.get('name') or ''} {payload.get('headline') or ''}".lower()
        if query.strip() and query.strip().lower() not in haystack:
            continue
        results.append({**payload, "user_id": target})
    return {"people": results}


def invite_to_group(user_id: str, group_id: str, invitee_user_id: str, message: str | None) -> dict:
    member = _require_member(group_id, user_id)
    if member.get("role") != "owner":
        raise HTTPException(403, "Only the group owner can invite people")
    _group(group_id)
    if invitee_user_id == user_id or not _connected(user_id, invitee_user_id):
        raise HTTPException(409, "Invitees must be an accepted Card connection")
    if _member(group_id, invitee_user_id):
        raise HTTPException(409, "That Card is already in the group")
    try:
        invitation = _sb().table("group_invitations").insert({
            "group_id": group_id,
            "invitee_user_id": invitee_user_id,
            "inviter_user_id": user_id,
            "message": (message or "").strip()[:500] or None,
        }).execute().data or []
    except Exception as exc:
        if getattr(exc, "code", None) == "23505" or "duplicate key" in str(exc).lower():
            raise HTTPException(409, "That Card already has a pending group invitation") from exc
        raise
    if not invitation:
        raise HTTPException(500, "Could not create group invitation")
    return {"invitation": invitation[0]}


def list_invitations(user_id: str, group_id: str) -> dict:
    member = _require_member(group_id, user_id)
    if member.get("role") != "owner":
        raise HTTPException(403, "Only the group owner can view invitations")
    rows = _sb().table("group_invitations").select("*").eq("group_id", group_id).eq("status", "pending").order("created_at", desc=True).execute().data or []
    return {"invitations": rows}


def list_incoming_invitations(user_id: str) -> dict:
    rows = _sb().table("group_invitations").select("*").eq("invitee_user_id", user_id).eq("status", "pending").order("created_at", desc=True).execute().data or []
    now = datetime.now(timezone.utc)
    live = []
    for row in rows:
        if row.get("expires_at") and datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) <= now:
            _sb().table("group_invitations").update({"status": "expired", "decided_at": _now()}).eq("id", row["id"]).execute()
            continue
        live.append(row)
    return {"invitations": live}


def respond_invitation(user_id: str, invitation_id: str, decision: str) -> dict:
    if decision not in {"accept", "decline"}:
        raise HTTPException(400, "decision must be accept or decline")
    rows = _sb().table("group_invitations").select("*").eq("id", invitation_id).limit(1).execute().data or []
    if not rows or rows[0]["invitee_user_id"] != user_id:
        raise HTTPException(404, "Invitation not found")
    invitation = rows[0]
    if invitation["status"] != "pending":
        raise HTTPException(409, "Invitation already resolved")
    if decision == "decline":
        _sb().table("group_invitations").update({"status": "declined", "decided_at": _now()}).eq("id", invitation_id).execute()
        return {"status": "declined", "group_id": invitation["group_id"]}
    if _member(invitation["group_id"], user_id):
        raise HTTPException(409, "You are already a group member")
    count = _sb().table("group_members").select("id", count="exact").eq("group_id", invitation["group_id"]).execute()
    if (getattr(count, "count", None) or len(count.data or [])) >= MAX_GROUP_MEMBERS:
        raise HTTPException(409, "This group is full")
    _sb().table("group_members").insert({"group_id": invitation["group_id"], "user_id": user_id, "role": "member", "invited_by": invitation["inviter_user_id"]}).execute()
    _sb().table("group_invitations").update({"status": "accepted", "decided_at": _now()}).eq("id", invitation_id).execute()
    return {"status": "accepted", "group_id": invitation["group_id"]}


def list_group_messages(user_id: str, group_id: str, limit: int = 100) -> dict:
    _require_member(group_id, user_id)
    rows = (_sb().table("group_messages").select("*").eq("group_id", group_id).order("created_at", desc=True).limit(max(1, min(limit, 500))).execute().data or [])
    return {"messages": list(reversed(rows))}


def send_group_message(user_id: str, group_id: str, content: str) -> dict:
    _require_member(group_id, user_id)
    text = content.strip()
    if not text:
        raise HTTPException(400, "Message cannot be empty")
    inserted = _sb().table("group_messages").insert({"group_id": group_id, "sender_user_id": user_id, "content": text[:4000]}).execute()
    _sb().table("groups").update({"updated_at": _now()}).eq("id", group_id).execute()
    return {"message": (inserted.data or [None])[0]}
