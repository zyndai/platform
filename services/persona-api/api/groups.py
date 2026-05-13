"""
Persona Groups API — bounded chat rooms shared by 3–15 personas.

MVP scope is human chat only:
  POST   /api/groups/                  create a group (you become owner)
  GET    /api/groups/                  list groups you're a member of
  GET    /api/groups/{id}              read one group
  PATCH  /api/groups/{id}              update name / description / visibility
  DELETE /api/groups/{id}              archive (soft delete, owner only)

  GET    /api/groups/{id}/members      list roster (members-only)
  POST   /api/groups/{id}/members      add a member by user_id (admin/owner only)
  PATCH  /api/groups/{id}/members/{uid}  change role / permissions
  DELETE /api/groups/{id}/members/{uid}  remove (or leave, if uid == self)

  GET    /api/groups/{id}/messages     paginated history (members-only)
  POST   /api/groups/{id}/messages     post a human message (members-only)

  POST   /api/groups/{id}/invite       generate or rotate an invite token
  GET    /api/groups/by-invite/{token} public preview for the join page
  POST   /api/groups/by-invite/{token}/join  join the group (auth required)

Non-members always see 404, never 403 — same fingerprinting defense used on
the public persona card. The service-role client lets the API enforce
membership in Python (RLS is defense-in-depth for direct frontend reads
of the realtime channel).

Phase 2 (proactive personas) will:
  * write `channel='agent'` rows from the orchestrator's group dispatcher,
  * use persona_group_members.permissions to decide whether a member's
    persona may answer brief / calendar questions inside the group.
The schema already carries both — no migration needed when that lands.
"""

import asyncio
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field
from supabase import create_client

import config
from api.auth import get_current_user

router = APIRouter()


def _supabase():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _is_missing_table(err: APIError) -> bool:
    return getattr(err, "code", None) == "PGRST205"


# ── Slug + invite token helpers ─────────────────────────────────────────
_SLUG_BAD = re.compile(r"[^a-z0-9-]+")
_SLUG_TRIM = re.compile(r"-{2,}")


def _slugify(name: str) -> str:
    base = _SLUG_BAD.sub("-", name.strip().lower())
    base = _SLUG_TRIM.sub("-", base).strip("-")
    return base[:48] or "group"


def _unique_slug(sb, candidate: str) -> str:
    """Try `slug`, then `slug-2`, `slug-3`, … until one isn't taken."""
    slug = candidate
    suffix = 2
    while True:
        existing = sb.table("persona_groups").select("id").eq("slug", slug).limit(1).execute()
        if not existing.data:
            return slug
        slug = f"{candidate}-{suffix}"
        suffix += 1
        if suffix > 50:
            # Belt-and-suspenders against an unlikely worst case; never expected.
            return f"{candidate}-{secrets.token_hex(3)}"


def _new_invite_token() -> str:
    return secrets.token_urlsafe(18)


# ── Membership helpers ──────────────────────────────────────────────────
def _membership(sb, group_id: str, user_id: str) -> dict | None:
    r = (
        sb.table("persona_group_members")
        .select("*")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


def _require_member(sb, group_id: str, user_id: str) -> dict:
    """Return the membership row; 404 if not a member.

    404 not 403 — keeps the group id un-fingerprintable to outsiders.
    The same group is invisible to someone who was never added.
    """
    m = _membership(sb, group_id, user_id)
    if not m:
        raise HTTPException(status_code=404, detail="Group not found.")
    return m


def _require_role(membership: dict, allowed: tuple[str, ...]) -> None:
    if membership.get("role") not in allowed:
        raise HTTPException(status_code=403, detail="Not allowed.")


def _resolve_agent_id(sb, user_id: str) -> str | None:
    """Look up the user's deployed persona agent_id, if any."""
    r = (
        sb.table("persona_agents")
        .select("agent_id")
        .eq("user_id", user_id)
        .eq("active", True)
        .limit(1)
        .execute()
    )
    return (r.data or [{}])[0].get("agent_id")


def _resolve_display_name(user: dict) -> str:
    meta = user.get("user_metadata") or {}
    return (
        meta.get("full_name")
        or meta.get("name")
        or (user.get("email") or "").split("@")[0]
        or "Someone"
    )


# ── Pydantic models ─────────────────────────────────────────────────────
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    visibility: str = Field(default="private", pattern="^(private|open)$")


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = None
    visibility: str | None = Field(default=None, pattern="^(private|open)$")


class MemberAdd(BaseModel):
    user_id: str
    role: str = Field(default="member", pattern="^(member|admin)$")


class MemberUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(member|admin)$")
    permissions: dict | None = None


class MessagePost(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reply_to: str | None = None


# ── CRUD: groups ────────────────────────────────────────────────────────
@router.post("/")
async def create_group(body: GroupCreate, user: dict = Depends(get_current_user)):
    """Create a group; caller becomes the owner."""
    sb = _supabase()
    slug = _unique_slug(sb, _slugify(body.name))
    invite_token = _new_invite_token()

    try:
        # The seed index is a monotonically increasing counter scoped to
        # groups (not personas) so phase 2's HD-derived group keypair
        # never collides with a persona's. Off-by-one against persona
        # derivation_index is fine — they live in disjoint domains.
        count_resp = sb.table("persona_groups").select("id", count="exact").execute()
        next_index = (getattr(count_resp, "count", None) or len(count_resp.data or [])) + 1

        group_row = (
            sb.table("persona_groups")
            .insert({
                "name": body.name.strip(),
                "description": (body.description or "").strip() or None,
                "slug": slug,
                "owner_user_id": user["id"],
                "visibility": body.visibility,
                "invite_token": invite_token,
                "group_seed_index": next_index,
            })
            .execute()
        )
    except APIError as e:
        if _is_missing_table(e):
            raise HTTPException(
                status_code=503,
                detail="Groups aren't provisioned yet — run patch_add_persona_groups.sql.",
            )
        raise
    if not group_row.data:
        raise HTTPException(status_code=500, detail="Couldn't create group.")
    group = group_row.data[0]

    agent_id = _resolve_agent_id(sb, user["id"])
    sb.table("persona_group_members").insert({
        "group_id": group["id"],
        "user_id": user["id"],
        "agent_id": agent_id,
        "role": "owner",
        "permissions": {
            # Owner gets everything by default; can tighten later.
            "can_see_brief": True,
            "can_query_calendar": True,
            "can_post": True,
            "can_invite": True,
            "can_speak_for_group": True,
        },
        "invited_by": user["id"],
    }).execute()

    return {"group": group}


@router.get("/")
async def list_my_groups(user: dict = Depends(get_current_user)):
    """Return all groups the caller belongs to, newest activity first."""
    sb = _supabase()
    try:
        memberships = (
            sb.table("persona_group_members")
            .select("group_id, role, joined_at")
            .eq("user_id", user["id"])
            .execute()
        )
    except APIError as e:
        if _is_missing_table(e):
            return {"groups": []}
        raise
    rows = memberships.data or []
    if not rows:
        return {"groups": []}

    ids = [r["group_id"] for r in rows]
    groups = (
        sb.table("persona_groups")
        .select("id, slug, name, description, avatar_url, visibility, created_at, updated_at, archived_at")
        .in_("id", ids)
        .is_("archived_at", "null")
        .order("updated_at", desc=True)
        .execute()
    )
    role_by_id = {r["group_id"]: r["role"] for r in rows}
    out = []
    for g in groups.data or []:
        out.append({**g, "my_role": role_by_id.get(g["id"])})
    return {"groups": out}


@router.get("/{group_id}")
async def get_group(group_id: str, user: dict = Depends(get_current_user)):
    sb = _supabase()
    _require_member(sb, group_id, user["id"])
    g = sb.table("persona_groups").select("*").eq("id", group_id).limit(1).execute()
    if not g.data:
        raise HTTPException(status_code=404, detail="Group not found.")
    group = g.data[0]
    if group.get("archived_at"):
        raise HTTPException(status_code=404, detail="Group not found.")
    counts = (
        sb.table("persona_group_members")
        .select("id", count="exact")
        .eq("group_id", group_id)
        .execute()
    )
    member_count = getattr(counts, "count", None) or len(counts.data or [])
    return {"group": group, "member_count": member_count}


@router.patch("/{group_id}")
async def update_group(
    group_id: str,
    body: GroupUpdate,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner", "admin"))

    patch: dict = {}
    if body.name is not None:
        patch["name"] = body.name.strip()
    if body.description is not None:
        patch["description"] = body.description.strip() or None
    if body.avatar_url is not None:
        patch["avatar_url"] = body.avatar_url or None
    if body.visibility is not None:
        patch["visibility"] = body.visibility
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    r = sb.table("persona_groups").update(patch).eq("id", group_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Group not found.")
    return {"group": r.data[0]}


@router.delete("/{group_id}")
async def archive_group(group_id: str, user: dict = Depends(get_current_user)):
    """Owner-only soft delete. Members can no longer see it; data is kept."""
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner",))
    sb.table("persona_groups").update({
        "archived_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", group_id).execute()
    return {"status": "archived"}


# ── Members ─────────────────────────────────────────────────────────────
@router.get("/{group_id}/members")
async def list_members(group_id: str, user: dict = Depends(get_current_user)):
    sb = _supabase()
    _require_member(sb, group_id, user["id"])

    rows = (
        sb.table("persona_group_members")
        .select("user_id, agent_id, role, permissions, joined_at")
        .eq("group_id", group_id)
        .order("joined_at")
        .execute()
    )
    members = rows.data or []
    if not members:
        return {"members": []}

    # Hydrate each row with a display name + avatar from persona_agents
    # (preferred) or auth.users.user_metadata (fallback for users whose
    # persona row didn't capture an avatar).
    user_ids = [m["user_id"] for m in members]
    personas = (
        sb.table("persona_agents")
        .select("user_id, name, profile")
        .in_("user_id", user_ids)
        .execute()
    )
    persona_by_uid = {p["user_id"]: p for p in (personas.data or [])}

    for m in members:
        p = persona_by_uid.get(m["user_id"]) or {}
        profile = p.get("profile") or {}
        m["display_name"] = p.get("name") or "Someone"
        m["avatar_url"] = profile.get("avatar_url") or profile.get("picture")
    return {"members": members}


@router.post("/{group_id}/members")
async def add_member(
    group_id: str,
    body: MemberAdd,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner", "admin"))

    if body.user_id == user["id"] or _membership(sb, group_id, body.user_id):
        raise HTTPException(status_code=409, detail="Already a member.")

    agent_id = _resolve_agent_id(sb, body.user_id)
    inserted = sb.table("persona_group_members").insert({
        "group_id": group_id,
        "user_id": body.user_id,
        "agent_id": agent_id,
        "role": body.role,
        "invited_by": user["id"],
    }).execute()
    return {"member": inserted.data[0] if inserted.data else None}


@router.patch("/{group_id}/members/{member_uid}")
async def update_member(
    group_id: str,
    member_uid: str,
    body: MemberUpdate,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    me = _require_member(sb, group_id, user["id"])
    _require_role(me, ("owner", "admin"))

    target = _membership(sb, group_id, member_uid)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found.")
    if target.get("role") == "owner" and member_uid != user["id"]:
        raise HTTPException(status_code=403, detail="Can't modify the owner.")

    patch: dict = {}
    if body.role is not None:
        patch["role"] = body.role
    if body.permissions is not None:
        patch["permissions"] = {**(target.get("permissions") or {}), **body.permissions}
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    r = (
        sb.table("persona_group_members")
        .update(patch)
        .eq("group_id", group_id)
        .eq("user_id", member_uid)
        .execute()
    )
    return {"member": r.data[0] if r.data else None}


@router.delete("/{group_id}/members/{member_uid}")
async def remove_member(
    group_id: str,
    member_uid: str,
    user: dict = Depends(get_current_user),
):
    """
    Remove a member from a group.

    Self-removal (leaving) is always allowed unless the caller is the
    owner — owners must transfer ownership or archive the group instead.
    Removing someone else requires owner/admin.
    """
    sb = _supabase()
    me = _require_member(sb, group_id, user["id"])
    target = _membership(sb, group_id, member_uid)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found.")

    if member_uid == user["id"]:
        if me.get("role") == "owner":
            raise HTTPException(
                status_code=400,
                detail="The owner can't leave — archive the group or transfer ownership first.",
            )
    else:
        _require_role(me, ("owner", "admin"))
        if target.get("role") == "owner":
            raise HTTPException(status_code=403, detail="Can't remove the owner.")

    sb.table("persona_group_members").delete().eq("group_id", group_id).eq("user_id", member_uid).execute()
    return {"status": "removed"}


# ── Messages ────────────────────────────────────────────────────────────
@router.get("/{group_id}/messages")
async def list_messages(
    group_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    before: str | None = Query(default=None, description="ISO-8601 cursor — return messages strictly older than this."),
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    _require_member(sb, group_id, user["id"])

    q = (
        sb.table("persona_group_messages")
        .select("*")
        .eq("group_id", group_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if before:
        q = q.lt("created_at", before)
    rows = q.execute()
    # Reverse so the client gets oldest-first (chat reading order).
    out = list(reversed(rows.data or []))
    return {"messages": out, "count": len(out)}


@router.post("/{group_id}/messages")
async def post_message(
    group_id: str,
    body: MessagePost,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])

    perms = m.get("permissions") or {}
    if perms.get("can_post") is False:
        raise HTTPException(status_code=403, detail="You can't post in this group.")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message can't be empty.")

    row = sb.table("persona_group_messages").insert({
        "group_id": group_id,
        "sender_user_id": user["id"],
        "sender_agent_id": m.get("agent_id"),
        "sender_name": _resolve_display_name(user),
        "channel": "human",
        "content": content,
        "reply_to": body.reply_to,
    }).execute()

    # Touch updated_at so list_my_groups orders by recent activity.
    sb.table("persona_groups").update({
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", group_id).execute()

    return {"message": row.data[0] if row.data else None}


# ── Invites ─────────────────────────────────────────────────────────────
@router.post("/{group_id}/invite")
async def rotate_invite(group_id: str, user: dict = Depends(get_current_user)):
    """Generate a fresh invite token. Older token stops working."""
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    perms = m.get("permissions") or {}
    if m.get("role") not in ("owner", "admin") and not perms.get("can_invite"):
        raise HTTPException(status_code=403, detail="Not allowed to issue invites.")

    token = _new_invite_token()
    r = (
        sb.table("persona_groups")
        .update({"invite_token": token, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", group_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(status_code=404, detail="Group not found.")
    return {"invite_token": token, "slug": r.data[0]["slug"]}


@router.get("/by-invite/{token}")
async def preview_invite(token: str):
    """
    Public, unauthenticated preview for the /g/[slug]/[token] join page.

    Returns only the safe-for-strangers fields (name, description, member
    count, avatar). A bad / rotated token returns 404 — same shape as a
    truly missing group, so attackers can't probe the token space.
    """
    sb = _supabase()
    try:
        r = (
            sb.table("persona_groups")
            .select("id, slug, name, description, avatar_url, visibility")
            .eq("invite_token", token)
            .is_("archived_at", "null")
            .limit(1)
            .execute()
        )
    except APIError as e:
        if _is_missing_table(e):
            raise HTTPException(status_code=404, detail="Invite not found.")
        raise
    if not r.data:
        raise HTTPException(status_code=404, detail="Invite not found.")
    g = r.data[0]
    counts = (
        sb.table("persona_group_members")
        .select("id", count="exact")
        .eq("group_id", g["id"])
        .execute()
    )
    return {
        "group": g,
        "member_count": getattr(counts, "count", None) or len(counts.data or []),
    }


@router.post("/by-invite/{token}/join")
async def join_via_invite(token: str, user: dict = Depends(get_current_user)):
    sb = _supabase()
    r = (
        sb.table("persona_groups")
        .select("id, slug")
        .eq("invite_token", token)
        .is_("archived_at", "null")
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(status_code=404, detail="Invite not found.")
    group = r.data[0]

    if _membership(sb, group["id"], user["id"]):
        return {"status": "already_member", "group_id": group["id"], "slug": group["slug"]}

    agent_id = _resolve_agent_id(sb, user["id"])
    sb.table("persona_group_members").insert({
        "group_id": group["id"],
        "user_id": user["id"],
        "agent_id": agent_id,
        "role": "member",
        "invited_by": None,
    }).execute()
    sb.table("persona_groups").update({
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", group["id"]).execute()
    return {"status": "joined", "group_id": group["id"], "slug": group["slug"]}
