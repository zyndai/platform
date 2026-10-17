"""Authenticated MCP operations for Persona Groups.

Every add-member operation exposed here creates an invitation. Membership is
only created by the invitee's accept operation, so the MCP path cannot silently
add another person to a group.
"""

from __future__ import annotations

from app.services import persona


async def create_group(uid: str, name: str, description: str = "", visibility: str = "private") -> dict:
    return await persona.group_request(
        "POST",
        uid,
        "",
        json={"name": name, "description": description or None, "visibility": visibility},
    )


async def list_groups(uid: str) -> dict:
    return await persona.group_request("GET", uid, "")


async def invite_to_group(
    uid: str,
    group_id: str,
    invitee_user_id: str,
    role: str = "member",
    message: str = "",
) -> dict:
    return await persona.group_request(
        "POST",
        uid,
        f"/{group_id}/invitations",
        json={
            "user_id": invitee_user_id,
            "role": role,
            "message": message or None,
        },
    )


async def list_group_invitations(uid: str, group_id: str) -> dict:
    return await persona.group_request("GET", uid, f"/{group_id}/invitations")


async def list_incoming_invitations(uid: str) -> dict:
    return await persona.group_request("GET", uid, "/invitations/incoming")


async def respond_to_invitation(uid: str, invitation_id: str, decision: str, confirm: bool = False) -> dict:
    if not confirm:
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "Set confirm=true after the user explicitly approves this group invitation decision.",
        }
    return await persona.group_request(
        "POST",
        uid,
        f"/invitations/{invitation_id}/respond",
        json={"decision": decision},
    )


async def list_members(uid: str, group_id: str) -> dict:
    return await persona.group_request("GET", uid, f"/{group_id}/members")


async def read_messages(uid: str, group_id: str, limit: int = 100) -> dict:
    bounded = max(1, min(int(limit), 500))
    return await persona.group_request("GET", uid, f"/{group_id}/messages?limit={bounded}")


async def send_message(uid: str, group_id: str, content: str) -> dict:
    return await persona.group_request(
        "POST",
        uid,
        f"/{group_id}/messages",
        json={"content": content},
    )
