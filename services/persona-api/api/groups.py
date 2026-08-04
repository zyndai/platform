from __future__ import annotations
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
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field
import config

import config
from api.auth import get_current_user

router = APIRouter()

def _supabase():
    return config.get_supabase()

def _is_missing_table(err: APIError) -> bool:
    return getattr(err, "code", None) == "PGRST205"

def _post_group_system_note(sb, group_id: str, note: str) -> None:
    """Best-effort system message into the group chat. Failure is swallowed."""
    try:
        sb.table("persona_group_messages").insert({
            "group_id": group_id,
            "channel": "system",
            "sender_name": "Zynd",
            "content": note,
        }).execute()
    except Exception as e:
        logger.warning(f"[groups] couldn't post system note in {group_id}: {e}")

# Soft cap. Phase 1's design target was small teams of 3–15. We don't want
# someone accidentally inviting their entire org and tipping the page into
# unbounded fan-out — the @-mention dispatcher fires one orchestrator call
# per mentioned member, and the calendar overlay scopes (phase 3) scale
# with member count too. Owners hit this cap before they hit something
# the system can't recover from gracefully.
MAX_GROUP_MEMBERS = 15

def _enforce_member_cap(sb, group_id: str) -> None:
    """Raise 409 if the group is at the soft cap."""
    counts = (
        sb.table("persona_group_members")
        .select("id", count="exact")
        .eq("group_id", group_id)
        .execute()
    )
    current = getattr(counts, "count", None) or len(counts.data or [])
    if current >= MAX_GROUP_MEMBERS:
        raise HTTPException(
            status_code=409,
            detail=f"This group is at the {MAX_GROUP_MEMBERS}-member limit.",
        )

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

GROUP_PERMISSION_DEFAULTS: dict[str, bool] = {
    "can_see_brief": False,
    "can_see_member_briefs": False,
    "can_see_group_brief": True,
    "can_query_calendar": True,
    "can_post": True,
    "can_invite": False,
    "can_speak_for_group": False,
}
GROUP_PERMISSION_KEYS = set(GROUP_PERMISSION_DEFAULTS.keys())

def _normalize_group_permissions(perms: dict | None, role: str | None = None) -> dict:
    """
    Return the current group permission shape with legacy values mapped in.

    Older rows used one broad `can_see_brief` flag. The new model splits that:
      * can_see_member_briefs — may receive private details from mentioned users
      * can_see_group_brief   — may read/use the shared team brief

    Missing `can_see_group_brief` defaults to True to preserve the original
    "any member can read the shared group brief" behavior until a manager
    explicitly turns it off for someone.
    """
    raw = perms or {}
    out = {**GROUP_PERMISSION_DEFAULTS, **raw}
    if "can_see_member_briefs" not in raw and "can_see_brief" in raw:
        out["can_see_member_briefs"] = bool(raw.get("can_see_brief"))
    if "can_see_group_brief" not in raw:
        out["can_see_group_brief"] = True
    if role == "owner":
        out.update({
            "can_see_member_briefs": True,
            "can_see_group_brief": True,
            "can_query_calendar": True,
            "can_post": True,
            "can_invite": True,
            "can_speak_for_group": True,
        })
    return out

def _permissions_for_member_row(member: dict) -> dict:
    return _normalize_group_permissions(member.get("permissions"), member.get("role"))

def _can_see_member_briefs(perms: dict | None) -> bool:
    return bool(_normalize_group_permissions(perms).get("can_see_member_briefs"))

def _can_see_group_brief(perms: dict | None) -> bool:
    return bool(_normalize_group_permissions(perms).get("can_see_group_brief"))

# ── Pydantic models ─────────────────────────────────────────────────────
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    visibility: str = Field(default="private", pattern="^(private|open)$")

class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    avatar_url: Optional[str] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|open)$")
    join_domain: Optional[str] = Field(default=None, max_length=120)

class MemberAdd(BaseModel):
    user_id: str
    role: str = Field(default="member", pattern="^(member|admin)$")

class MemberUpdate(BaseModel):
    role: Optional[str] = Field(default=None, pattern="^(member|admin)$")
    permissions: Optional[dict] = None

class MessagePost(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reply_to: Optional[str] = None
    time_zone: Optional[str] = None

class InvitationCreate(BaseModel):
    user_id: str
    role: str = Field(default="member", pattern="^(member|admin)$")
    message: Optional[str] = Field(default=None, max_length=500)

class InvitationDecide(BaseModel):
    decision: str = Field(pattern="^(accept|decline)$")

# ── CRUD: groups ────────────────────────────────────────────────────────
@router.post("/")
async def create_group(body: GroupCreate, user: dict = Depends(get_current_user)):
    """Create a group; caller becomes the owner."""
    sb = _supabase()
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name can't be empty.")
    description = (body.description or "").strip() or None
    slug = _unique_slug(sb, _slugify(name))
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
                "name": name,
                "description": description,
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

    try:
        agent_id = _resolve_agent_id(sb, user["id"])
        sb.table("persona_group_members").insert({
            "group_id": group["id"],
            "user_id": user["id"],
            "agent_id": agent_id,
            "role": "owner",
            "permissions": _normalize_group_permissions(None, "owner"),
            "invited_by": user["id"],
        }).execute()
    except Exception:
        logger.exception(f"[groups] owner membership insert failed for {group['id']}, rolling back")
        try:
            sb.table("persona_groups").delete().eq("id", group["id"]).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Couldn't set up group membership.")

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

# ── Discoverable groups (phase 5) ──────────────────────────────────────
# Static one-segment routes must be registered before `/{group_id}`.
# Starlette matches routes in declaration order, so putting `/discover`
# after `/{group_id}` makes the discovery endpoint look like a missing
# group with id="discover".
@router.get("/discover")
async def discover_groups(
    query: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    """
    Return open, non-archived groups the caller isn't already a member of.

    Lightweight — doesn't expose member counts or roster. The /by-invite
    flow handles the actual join.
    """
    sb = _supabase()

    try:
        # Mine, to exclude.
        mine = (
            sb.table("persona_group_members")
            .select("group_id")
            .eq("user_id", user["id"])
            .execute()
        )
        my_group_ids = {r["group_id"] for r in (mine.data or [])}

        builder = (
            sb.table("persona_groups")
            .select("id, slug, name, description, avatar_url, visibility, join_domain, invite_token, created_at")
            .eq("visibility", "open")
            .is_("archived_at", "null")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if query:
            pattern = f"%{query.strip()}%"
            builder = builder.or_(f"name.ilike.{pattern},description.ilike.{pattern}")
        rows = builder.execute()
    except APIError as e:
        if _is_missing_table(e):
            return {"groups": []}
        raise

    eligible = [g for g in (rows.data or []) if g["id"] not in my_group_ids]

    member_counts: dict[str, int] = {}
    if eligible:
        from collections import Counter
        try:
            counts_resp = (
                sb.table("persona_group_members")
                .select("group_id")
                .in_("group_id", [g["id"] for g in eligible])
                .execute()
            )
            member_counts = dict(Counter(r["group_id"] for r in (counts_resp.data or [])))
        except Exception:
            pass

    out = []
    for g in eligible:
        out.append({
            "id": g["id"],
            "slug": g["slug"],
            "name": g["name"],
            "description": g.get("description"),
            "avatar_url": g.get("avatar_url"),
            "join_domain": g.get("join_domain"),
            "invite_token": g.get("invite_token"),
            "member_count": member_counts.get(g["id"], 0),
            "created_at": g["created_at"],
        })
    return {"groups": out}

@router.get("/auto-join-candidates")
async def auto_join_candidates(user: dict = Depends(get_current_user)):
    """
    Open groups whose ``join_domain`` matches the caller's email domain.

    Returned as a short list with the invite token so the frontend can
    one-click join — same code path as following a regular invite link.
    """
    email = (user.get("email") or "").lower().strip()
    if "@" not in email:
        return {"groups": []}
    domain = email.rsplit("@", 1)[-1]
    if not domain:
        return {"groups": []}

    sb = _supabase()
    try:
        mine = (
            sb.table("persona_group_members")
            .select("group_id")
            .eq("user_id", user["id"])
            .execute()
        )
        my_group_ids = {r["group_id"] for r in (mine.data or [])}

        rows = (
            sb.table("persona_groups")
            .select("id, slug, name, description, avatar_url, invite_token, join_domain")
            .eq("visibility", "open")
            .eq("join_domain", domain)
            .is_("archived_at", "null")
            .execute()
        )
    except APIError as e:
        if _is_missing_table(e):
            return {"groups": []}
        raise

    out = [g for g in (rows.data or []) if g["id"] not in my_group_ids]
    return {"groups": out, "domain": domain}

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
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Group name can't be empty.")
        patch["name"] = name
    if body.description is not None:
        patch["description"] = body.description.strip() or None
    if body.avatar_url is not None:
        patch["avatar_url"] = body.avatar_url or None
    if body.visibility is not None:
        patch["visibility"] = body.visibility
    if body.join_domain is not None:
        # Normalize: lowercase, strip an optional leading "@", reject
        # obviously malformed values. Empty string clears the rule.
        raw = (body.join_domain or "").strip().lstrip("@").lower()
        if raw and "." not in raw:
            raise HTTPException(status_code=400, detail="join_domain must look like 'acme.com'.")
        patch["join_domain"] = raw or None
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

async def _migrate_group_brief(
    *,
    sb,
    group_id: str,
    old_owner_user_id: str,
    new_owner_user_id: str,
    group_data: dict,
) -> None:
    """
    Copy the group brief Google Doc into the new owner's Drive after an
    ownership transfer. Best-effort: logs and returns on any failure so the
    transfer itself is never rolled back.
    """
    old_doc_id = group_data["brief_doc_id"]
    group_name = group_data.get("name") or "Group"

    def _run() -> None:
        try:
            from mcp.tools.google.docs import append_to_document, create_document, read_document
            fetched = read_document(user_id=old_owner_user_id, document_id=old_doc_id)
            if not fetched.get("success"):
                logger.warning(
                    f"[groups] brief migration: couldn't read old doc {old_doc_id} for {group_id}: "
                    f"{fetched.get('error')}"
                )
                return
            content = (fetched.get("content") or "").strip()
            created = create_document(user_id=new_owner_user_id, title=f"Group brief — {group_name}")
            if not created.get("success"):
                logger.warning(
                    f"[groups] brief migration: couldn't create new doc for {group_id}: "
                    f"{created.get('error')}"
                )
                return
            new_doc_id = created["document_id"]
            new_doc_url = created.get("link", "")
            if content:
                appended = append_to_document(
                    user_id=new_owner_user_id, document_id=new_doc_id, text=content
                )
                if not appended.get("success"):
                    logger.warning(
                        f"[groups] brief migration: content copy incomplete for {group_id}: "
                        f"{appended.get('error')}"
                    )
            sb.table("persona_groups").update({
                "brief_doc_id": new_doc_id,
                "brief_doc_url": new_doc_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", group_id).execute()
            logger.info(
                f"[groups] brief migrated {old_doc_id} → {new_doc_id} for group {group_id}"
            )
        except Exception as e:
            logger.warning(f"[groups] brief migration failed for {group_id}: {e}")

    await asyncio.to_thread(_run)

class OwnerTransfer(BaseModel):
    new_owner_user_id: str

class GroupBriefSave(BaseModel):
    content: str = Field(min_length=0, max_length=50000)

class GroupMeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start: str  # ISO 8601 UTC
    end: str    # ISO 8601 UTC
    description: Optional[str] = Field(default=None, max_length=2000)
    location: Optional[str] = Field(default=None, max_length=200)
    time_zone: Optional[str] = None
    member_user_ids: Optional[list[str]] = None  # opt-in; defaults to all members

CONSTRAINT_KINDS = ("fact", "rule", "voice")
MAX_CONSTRAINTS_PER_GROUP = 20

class GroupConstraintCreate(BaseModel):
    kind: str = Field(pattern="^(fact|rule|voice)$")
    text: str = Field(min_length=1, max_length=400)

class GroupConstraintUpdate(BaseModel):
    kind: Optional[str] = Field(default=None, pattern="^(fact|rule|voice)$")
    text: Optional[str] = Field(default=None, min_length=1, max_length=400)

@router.post("/{group_id}/transfer-owner")
async def transfer_owner(
    group_id: str,
    body: OwnerTransfer,
    user: dict = Depends(get_current_user),
):
    """
    Move ownership of a group from the current owner to another member.

    Two writes wrapped together: demote the old owner to admin, promote
    the named member to owner, and stamp owner_user_id on the group row
    so listing queries stay consistent. There's no DB transaction here
    (Supabase python client doesn't expose one cleanly), so the worst
    case on a partial failure is that the group ends up with two admins
    and the original owner — annoying but recoverable by re-running.
    """
    sb = _supabase()
    me = _require_member(sb, group_id, user["id"])
    _require_role(me, ("owner",))

    if body.new_owner_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You are already the owner.")

    target = _membership(sb, group_id, body.new_owner_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="That user isn't a member of this group.")

    sb.table("persona_group_members").update({"role": "admin"}).eq(
        "group_id", group_id
    ).eq("user_id", user["id"]).execute()
    sb.table("persona_group_members").update({"role": "owner"}).eq(
        "group_id", group_id
    ).eq("user_id", body.new_owner_user_id).execute()
    sb.table("persona_groups").update({
        "owner_user_id": body.new_owner_user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", group_id).execute()

    # Best-effort: migrate the group brief doc to the new owner's Drive.
    # The brief endpoint reads via owner credentials, so without this the
    # brief becomes unreadable once the old owner revokes Google access.
    g = sb.table("persona_groups").select("brief_doc_id, name").eq("id", group_id).limit(1).execute()
    if g.data and g.data[0].get("brief_doc_id"):
        asyncio.create_task(_migrate_group_brief(
            sb=sb,
            group_id=group_id,
            old_owner_user_id=user["id"],
            new_owner_user_id=body.new_owner_user_id,
            group_data=g.data[0],
        ))

    return {"status": "ok", "new_owner_user_id": body.new_owner_user_id}

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
        m["permissions"] = _normalize_group_permissions(m.get("permissions"), m.get("role"))
        m["display_name"] = p.get("name") or "Someone"
        avatar = profile.get("avatar_url") or profile.get("picture")
        if not avatar:
            try:
                import requests as _req
                admin_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{m['user_id']}"
                resp = _req.get(
                    admin_url,
                    headers={
                        "apikey": config.SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
                    },
                    timeout=3,
                )
                if resp.ok:
                    md = (resp.json() or {}).get("user_metadata") or {}
                    pic = md.get("avatar_url") or md.get("picture")
                    if isinstance(pic, str) and pic:
                        avatar = pic
            except Exception:
                pass
        m["avatar_url"] = avatar
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

    _enforce_member_cap(sb, group_id)

    agent_id = _resolve_agent_id(sb, body.user_id)
    inserted = sb.table("persona_group_members").insert({
        "group_id": group_id,
        "user_id": body.user_id,
        "agent_id": agent_id,
        "role": body.role,
        "permissions": _normalize_group_permissions(None, body.role),
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
    if target.get("role") == "owner":
        raise HTTPException(status_code=403, detail="Can't modify the owner.")

    patch: dict = {}
    if body.role is not None:
        patch["role"] = body.role
    if body.permissions is not None:
        unknown = set(body.permissions.keys()) - GROUP_PERMISSION_KEYS
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown permission key: {sorted(unknown)[0]}",
            )
        merged = {**_permissions_for_member_row(target), **body.permissions}
        if "can_see_member_briefs" in body.permissions:
            merged["can_see_brief"] = bool(body.permissions["can_see_member_briefs"])
        patch["permissions"] = merged
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

    perms = _permissions_for_member_row(m)
    if perms.get("can_post") is False:
        raise HTTPException(status_code=403, detail="You can't post in this group.")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message can't be empty.")

    asker_display = _resolve_display_name(user)
    row = sb.table("persona_group_messages").insert({
        "group_id": group_id,
        "sender_user_id": user["id"],
        "sender_agent_id": m.get("agent_id"),
        "sender_name": asker_display,
        "channel": "human",
        "content": content,
        "reply_to": body.reply_to,
    }).execute()

    sb.table("persona_groups").update({
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", group_id).execute()

    # Phase 2: detect @-mentions and fire the target personas off the
    # request path so the human's POST returns fast. The dispatcher posts
    # each reply back into persona_group_messages with channel='agent';
    # realtime delivers them to every subscriber, including the asker.
    #
    # Phase 3a: when the group has a brief doc, pre-fetch its content
    # once here (rather than per-dispatch) and pass into each target's
    # invocation. The fetch happens off the event loop because read_document
    # is sync; on failure we fall through with no brief context.
    mentioned_uids = _spawn_mention_dispatch(
        sb=sb,
        group_id=group_id,
        asker_user=user,
        asker_display=asker_display,
        asker_agent_id=m.get("agent_id"),
        asker_permissions=perms,
        message_content=content,
        time_zone=body.time_zone,
    )

    inserted = row.data[0] if row.data else None
    return {
        "message": inserted,
        "mentioned_user_ids": mentioned_uids,
    }

def _spawn_mention_dispatch(
    *,
    sb,
    group_id: str,
    asker_user: dict,
    asker_display: str,
    asker_agent_id: str | None,
    asker_permissions: dict,
    message_content: str,
    time_zone: Optional[str] = None,
) -> list[str]:
    """
    Parse @-mentions, resolve them to roster rows, and schedule a
    background dispatch for each. Returns the list of user_ids that will
    be invoked so the frontend can render a "X's persona is replying…"
    indicator until the realtime row arrives.

    Self-mention is filtered out — a member @-mentioning themselves
    shouldn't trigger their own persona to reply to them in their own
    voice.

    If the group has a brief doc, we read it once here and pass the
    content to each dispatch task so every target persona sees the same
    snapshot of the shared brief for this turn.
    """
    from agent.group_dispatch import (
        extract_mentions,
        resolve_mentions_to_members,
        dispatch_group_mention,
    )
    raw_mentions = extract_mentions(message_content)
    if not raw_mentions:
        return []

    asker_permissions = _normalize_group_permissions(asker_permissions)

    # Brief snapshot (phase 3a). Only fetched when the asker may use the
    # shared group brief — otherwise it would never reach the target's
    # prompt anyway (the dispatcher gates on the same flag). Owner's
    # Google connection is the read credential.
    group_brief_content: str | None = None
    if _can_see_group_brief(asker_permissions):
        try:
            grow = (
                sb.table("persona_groups")
                .select("owner_user_id, brief_doc_id")
                .eq("id", group_id)
                .limit(1)
                .execute()
            )
            if grow.data and grow.data[0].get("brief_doc_id"):
                owner_id = grow.data[0]["owner_user_id"]
                doc_id = grow.data[0]["brief_doc_id"]
                from mcp.tools.google.docs import read_document
                fetched = read_document(user_id=owner_id, document_id=doc_id)
                if fetched.get("success"):
                    group_brief_content = (fetched.get("content") or "").strip() or None
        except Exception:
            # Best-effort — a broken Drive connection or stale doc just
            # means the personas dispatch without the shared brief.
            group_brief_content = None

    # Group constraints (phase 4). Unlike the brief these aren't gated
    # by asker permissions — they're the team's shared guardrails that
    # apply to every persona's reply in the room regardless of who's
    # asking. Missing table (pre-migration) is treated as no constraints.
    group_constraints: list[dict] = []
    try:
        crows = (
            sb.table("persona_group_constraints")
            .select("kind, text")
            .eq("group_id", group_id)
            .is_("archived_at", "null")
            .execute()
        )
        group_constraints = crows.data or []
    except APIError as e:
        if not _is_missing_table(e):
            logger.warning(f"[group-dispatch] couldn't load constraints for {group_id}: {e}")

    roster = (
        sb.table("persona_group_members")
        .select("user_id, agent_id, role, permissions, joined_at")
        .eq("group_id", group_id)
        .order("joined_at")
        .execute()
    )
    members = roster.data or []
    if not members:
        return []

    # Hydrate display_name from persona_agents so resolve_mentions can match
    # against the same name the frontend renders.
    user_ids = [m["user_id"] for m in members]
    personas = (
        sb.table("persona_agents")
        .select("user_id, name")
        .in_("user_id", user_ids)
        .execute()
    )
    name_by_uid = {p["user_id"]: p.get("name") for p in (personas.data or [])}
    for mem in members:
        mem["display_name"] = name_by_uid.get(mem["user_id"]) or "Someone"

    resolved = resolve_mentions_to_members(raw_mentions, members)
    targets = [r for r in resolved if r["user_id"] != asker_user["id"]]
    if not targets:
        return []

    scheduled_user_ids: list[str] = []
    for target in targets:
        if not target.get("agent_id"):
            display = target.get("display_name") or "That member"
            _post_group_system_note(sb, group_id, f"{display} hasn't deployed a persona yet.")
            continue
        scheduled_user_ids.append(target["user_id"])
        # Audit (phase 5): shared group brief actually crosses to this
        # target's prompt. Only when group_brief_content is non-empty —
        # null content means nothing was read, so nothing to log.
        if group_brief_content:
            _log_audit_event(
                sb,
                group_id=group_id,
                affected_user_id=asker_user["id"],
                actor_user_id=asker_user["id"],
                kind="brief_shared",
                metadata={
                    "channel": "group_mention",
                    "source": "group_brief",
                    "target_user_id": target["user_id"],
                },
            )
        asyncio.create_task(
            dispatch_group_mention(
                group_id=group_id,
                asker_user_id=asker_user["id"],
                asker_display_name=asker_display,
                asker_agent_id=asker_agent_id,
                target_member=target,
                user_message=message_content,
                asker_permissions=asker_permissions,
                group_brief_content=group_brief_content,
                group_constraints=group_constraints,
                time_zone=time_zone,
            )
        )
    return scheduled_user_ids

# ── Invites ─────────────────────────────────────────────────────────────
@router.post("/{group_id}/invite")
async def rotate_invite(group_id: str, user: dict = Depends(get_current_user)):
    """Generate a fresh invite token. Older token stops working."""
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    perms = _permissions_for_member_row(m)
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

    _enforce_member_cap(sb, group["id"])

    agent_id = _resolve_agent_id(sb, user["id"])
    sb.table("persona_group_members").insert({
        "group_id": group["id"],
        "user_id": user["id"],
        "agent_id": agent_id,
        "role": "member",
        "permissions": _normalize_group_permissions(None, "member"),
        "invited_by": None,
    }).execute()
    sb.table("persona_groups").update({
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", group["id"]).execute()
    return {"status": "joined", "group_id": group["id"], "slug": group["slug"]}

# ── Invitations (search by name → inbox decision) ───────────────────────

def _require_invite_authority(sb, group_id: str, user_id: str) -> dict:
    m = _require_member(sb, group_id, user_id)
    if m.get("role") in ("owner", "admin"):
        return m
    if _permissions_for_member_row(m).get("can_invite"):
        return m
    raise HTTPException(status_code=403, detail="Not allowed to invite to this group.")

def _resolve_avatar_url(sb, user_id: str, profile: dict | None) -> str | None:
    p = profile or {}
    candidate = p.get("avatar_url") or p.get("picture")
    if candidate:
        return candidate
    try:
        import requests as _req
        admin_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
        resp = _req.get(
            admin_url,
            headers={
                "apikey": config.SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
            },
            timeout=3,
        )
        if resp.ok:
            md = (resp.json() or {}).get("user_metadata") or {}
            pic = md.get("avatar_url") or md.get("picture")
            if isinstance(pic, str) and pic:
                return pic
    except Exception:
        return None
    return None

def _hydrate_persona(sb, user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    rows = (
        sb.table("persona_agents")
        .select("user_id, agent_id, name, description, profile")
        .in_("user_id", user_ids)
        .eq("active", True)
        .execute()
    )
    return {r["user_id"]: r for r in (rows.data or [])}

def _hydrate_group_brief(sb, group_id: str) -> dict | None:
    r = (
        sb.table("persona_groups")
        .select("id, slug, name, description, avatar_url, visibility, archived_at")
        .eq("id", group_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        return None
    g = r.data[0]
    if g.get("archived_at"):
        return None
    counts = (
        sb.table("persona_group_members")
        .select("id", count="exact")
        .eq("group_id", group_id)
        .execute()
    )
    g["member_count"] = getattr(counts, "count", None) or len(counts.data or [])
    g.pop("archived_at", None)
    return g

@router.get("/{group_id}/invitable")
async def search_invitable_users(
    group_id: str,
    query: str = Query("", max_length=120),
    limit: int = Query(12, ge=1, le=40),
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    _require_invite_authority(sb, group_id, user["id"])

    members = (
        sb.table("persona_group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
    )
    excluded = {r["user_id"] for r in (members.data or [])}
    try:
        pending = (
            sb.table("persona_group_invitations")
            .select("invitee_user_id")
            .eq("group_id", group_id)
            .eq("status", "pending")
            .execute()
        )
        excluded |= {r["invitee_user_id"] for r in (pending.data or [])}
    except APIError as e:
        if not _is_missing_table(e):
            raise

    q = (query or "").strip()
    builder = (
        sb.table("persona_agents")
        .select("user_id, agent_id, name, description, profile")
        .eq("active", True)
        .order("name")
        .limit(limit)
    )
    if q:
        builder = builder.ilike("name", f"%{q}%")
    rows = builder.execute().data or []

    results = []
    for r in rows:
        uid = r.get("user_id")
        if not uid or uid in excluded or uid == user["id"]:
            continue
        results.append({
            "user_id": uid,
            "agent_id": r.get("agent_id"),
            "name": r.get("name") or "Persona",
            "description": r.get("description") or "",
            "avatar_url": _resolve_avatar_url(sb, uid, r.get("profile")),
        })
        if len(results) >= limit:
            break
    return {"results": results, "count": len(results)}

@router.post("/{group_id}/invitations")
async def create_invitation(
    group_id: str,
    body: InvitationCreate,
    user: dict = Depends(get_current_user),
):
    # Member cap is enforced at ACCEPT-time, not here — pending invites
    # don't consume a slot, so a group can have more pending than cap.
    sb = _supabase()
    inviter = _require_invite_authority(sb, group_id, user["id"])

    if body.user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You can't invite yourself.")
    if _membership(sb, group_id, body.user_id):
        raise HTTPException(status_code=409, detail="That user is already a member.")
    # Verify the invitee actually exists as a Zynd user — otherwise the FK
    # would block this, but we'd rather return a clean 404 than a 500.
    invitee_persona = _hydrate_persona(sb, [body.user_id]).get(body.user_id)
    if not invitee_persona:
        raise HTTPException(status_code=404, detail="That user doesn't have a deployed persona.")

    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    try:
        inserted = sb.table("persona_group_invitations").insert({
            "group_id": group_id,
            "invitee_user_id": body.user_id,
            "inviter_user_id": user["id"],
            "invitee_role": body.role,
            "status": "pending",
            "message": (body.message or "").strip() or None,
            "expires_at": expires_at,
        }).execute()
    except APIError as e:
        # 23505 — partial unique index `(group_id, invitee_user_id) WHERE status='pending'`
        if getattr(e, "code", None) == "23505" or "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="That user already has a pending invite for this group.",
            )
        if _is_missing_table(e):
            raise HTTPException(
                status_code=500,
                detail="Invitations table missing — run patch_add_persona_group_invitations.sql.",
            )
        raise

    row = (inserted.data or [None])[0]
    return {
        "invitation": _serialize_invitation(row, sb=sb, inviter=inviter) if row else None,
    }

@router.get("/{group_id}/invitations")
async def list_group_invitations(
    group_id: str,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    _require_invite_authority(sb, group_id, user["id"])
    try:
        rows = (
            sb.table("persona_group_invitations")
            .select("*")
            .eq("group_id", group_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        ).data or []
    except APIError as e:
        if _is_missing_table(e):
            return {"invitations": []}
        raise
    return {"invitations": [_serialize_invitation(r, sb=sb) for r in rows]}

@router.delete("/{group_id}/invitations/{invitation_id}")
async def revoke_invitation(
    group_id: str,
    invitation_id: str,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    _require_invite_authority(sb, group_id, user["id"])
    inv = (
        sb.table("persona_group_invitations")
        .select("*")
        .eq("id", invitation_id)
        .eq("group_id", group_id)
        .limit(1)
        .execute()
    )
    if not inv.data:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if inv.data[0].get("status") != "pending":
        raise HTTPException(status_code=409, detail="Invitation already resolved.")
    sb.table("persona_group_invitations").update({
        "status": "revoked",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", invitation_id).execute()
    return {"status": "revoked"}

@router.get("/invitations/incoming")
async def list_incoming_invitations(user: dict = Depends(get_current_user)):
    sb = _supabase()
    try:
        rows = (
            sb.table("persona_group_invitations")
            .select("*")
            .eq("invitee_user_id", user["id"])
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        ).data or []
    except APIError as e:
        if _is_missing_table(e):
            return {"invitations": []}
        raise

    # Filter out expired rows in-memory; no background sweep yet.
    now = datetime.now(timezone.utc)
    live: list[dict] = []
    for r in rows:
        exp = r.get("expires_at")
        if exp:
            try:
                if datetime.fromisoformat(exp.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass
        live.append(r)
    return {"invitations": [_serialize_invitation(r, sb=sb) for r in live]}

@router.post("/invitations/{invitation_id}/respond")
async def respond_to_invitation(
    invitation_id: str,
    body: InvitationDecide,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    inv_row = (
        sb.table("persona_group_invitations")
        .select("*")
        .eq("id", invitation_id)
        .limit(1)
        .execute()
    )
    if not inv_row.data:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    inv = inv_row.data[0]
    if inv["invitee_user_id"] != user["id"]:
        # Same 404 shape as a missing row — don't disclose existence.
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if inv.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Invitation already resolved.")

    exp = inv.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                sb.table("persona_group_invitations").update({
                    "status": "expired",
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", invitation_id).execute()
                raise HTTPException(status_code=410, detail="This invitation has expired.")
        except ValueError:
            pass

    now_iso = datetime.now(timezone.utc).isoformat()
    if body.decision == "decline":
        sb.table("persona_group_invitations").update({
            "status": "declined",
            "decided_at": now_iso,
        }).eq("id", invitation_id).execute()
        return {"status": "declined", "group_id": inv["group_id"]}

    group_id = inv["group_id"]
    if _membership(sb, group_id, user["id"]):
        sb.table("persona_group_invitations").update({
            "status": "accepted",
            "decided_at": now_iso,
        }).eq("id", invitation_id).execute()
        return {"status": "already_member", "group_id": group_id}

    _enforce_member_cap(sb, group_id)

    agent_id = _resolve_agent_id(sb, user["id"])
    role = inv.get("invitee_role") or "member"
    sb.table("persona_group_members").insert({
        "group_id": group_id,
        "user_id": user["id"],
        "agent_id": agent_id,
        "role": role,
        "permissions": _normalize_group_permissions(None, role),
        "invited_by": inv.get("inviter_user_id"),
    }).execute()
    sb.table("persona_group_invitations").update({
        "status": "accepted",
        "decided_at": now_iso,
    }).eq("id", invitation_id).execute()
    sb.table("persona_groups").update({
        "updated_at": now_iso,
    }).eq("id", group_id).execute()
    return {"status": "accepted", "group_id": group_id}

def _serialize_invitation(row: dict, *, sb, inviter: dict | None = None) -> dict:
    group = _hydrate_group_brief(sb, row["group_id"]) or {"id": row["group_id"]}
    invitee_uid = row.get("invitee_user_id")
    inviter_uid = row.get("inviter_user_id")
    uids = [u for u in (inviter_uid, invitee_uid) if u]
    personas = _hydrate_persona(sb, uids)
    inviter_persona = personas.get(inviter_uid) if inviter_uid else None
    invitee_persona = personas.get(invitee_uid) if invitee_uid else None
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "group": group,
        "invitee_user_id": invitee_uid,
        "invitee_name": (invitee_persona or {}).get("name"),
        "invitee_avatar_url": (
            _resolve_avatar_url(sb, invitee_uid, (invitee_persona or {}).get("profile"))
            if invitee_uid else None
        ),
        "inviter_user_id": inviter_uid,
        "inviter_name": (inviter_persona or {}).get("name"),
        "inviter_avatar_url": (
            _resolve_avatar_url(sb, inviter_uid, (inviter_persona or {}).get("profile"))
            if inviter_uid else None
        ),
        "invitee_role": row.get("invitee_role") or "member",
        "status": row.get("status") or "pending",
        "message": row.get("message"),
        "created_at": row.get("created_at"),
        "decided_at": row.get("decided_at"),
        "expires_at": row.get("expires_at"),
    }

# ── Group brief (phase 3a) ──────────────────────────────────────────────
# The shared Google Doc lives in the OWNER's Drive — that keeps the
# storage cost on the owner who creates the group, and makes deletion
# semantics obvious (revoke their Google access or archive the group →
# nobody reads the brief any longer). Reads are gated by the member's
# `can_see_group_brief` permission; writes go to owner/admin only.

@router.post("/{group_id}/brief/init")
async def init_group_brief(group_id: str, user: dict = Depends(get_current_user)):
    """
    Create a Google Doc that will hold the group's shared brief.
    Owner-only — the doc is created in their Drive and we don't have a
    transfer flow if ownership changes mid-life (the brief stays where
    it was created).
    """
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner",))

    g = sb.table("persona_groups").select("*").eq("id", group_id).limit(1).execute()
    if not g.data:
        raise HTTPException(status_code=404, detail="Group not found.")
    group = g.data[0]
    if group.get("archived_at"):
        raise HTTPException(status_code=404, detail="Group not found.")
    if group.get("brief_doc_id"):
        return {
            "doc_id": group["brief_doc_id"],
            "url": group.get("brief_doc_url") or "",
            "created": False,
        }

    def _run() -> dict:
        from mcp.tools.google.docs import create_document, append_to_document
        title = f"Group brief — {group['name']}"
        result = create_document(user_id=user["id"], title=title)
        if not result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "Couldn't create the group brief doc.",
            )
        doc_id = result["document_id"]
        doc_url = result["link"]

        # Seed with the description so the doc isn't a blank page.
        seed = (group.get("description") or "").strip()
        if seed:
            append_to_document(user_id=user["id"], document_id=doc_id, text=seed + "\n")

        sb.table("persona_groups").update({
            "brief_doc_id": doc_id,
            "brief_doc_url": doc_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", group_id).execute()
        return {"doc_id": doc_id, "url": doc_url, "created": True}

    return await asyncio.to_thread(_run)

@router.get("/{group_id}/brief")
async def get_group_brief(group_id: str, user: dict = Depends(get_current_user)):
    """
    Return the group's brief content when this member has group-brief access.

    Reads go directly to Google Docs (rather than serving a cached snapshot)
    so co-editors see each other's writes within a refresh. The brief is
    small enough (cap 50KB) that the latency hit is fine for the chat
    rail's polling cadence.
    """
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    if not _can_see_group_brief(_permissions_for_member_row(m)):
        raise HTTPException(status_code=403, detail="You don't have permission to read this group's shared brief.")

    g = sb.table("persona_groups").select("*").eq("id", group_id).limit(1).execute()
    if not g.data or g.data[0].get("archived_at"):
        raise HTTPException(status_code=404, detail="Group not found.")
    group = g.data[0]

    if not group.get("brief_doc_id"):
        return {"exists": False, "description": group.get("description") or ""}

    def _run() -> dict:
        from mcp.tools.google.docs import read_document
        fetched = read_document(user_id=group["owner_user_id"], document_id=group["brief_doc_id"])
        if not fetched.get("success"):
            return {
                "exists": True,
                "doc_id": group["brief_doc_id"],
                "url": group.get("brief_doc_url") or "",
                "content": "",
                "error": fetched.get("error"),
            }
        return {
            "exists": True,
            "doc_id": group["brief_doc_id"],
            "url": group.get("brief_doc_url") or "",
            "content": fetched.get("content") or "",
            "title": fetched.get("title"),
        }

    return await asyncio.to_thread(_run)

@router.patch("/{group_id}/brief")
async def save_group_brief(
    group_id: str,
    body: GroupBriefSave,
    user: dict = Depends(get_current_user),
):
    """
    Replace the brief body. Owner/admin only.

    The doc itself is owned by the group's `owner_user_id` — even an admin
    PATCHing here writes through that user's Google credentials, so a
    revoked owner connection is the canonical kill-switch for editing.
    """
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner", "admin"))

    g = sb.table("persona_groups").select("*").eq("id", group_id).limit(1).execute()
    if not g.data:
        raise HTTPException(status_code=404, detail="Group not found.")
    group = g.data[0]
    if not group.get("brief_doc_id"):
        raise HTTPException(status_code=400, detail="No brief doc yet — initialize it first.")

    def _run() -> dict:
        from mcp.tools.google.docs import replace_document_body
        result = replace_document_body(
            user_id=group["owner_user_id"],
            document_id=group["brief_doc_id"],
            text=body.content,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "Couldn't save the brief.",
            )
        sb.table("persona_groups").update({
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
        return {"success": True, "doc_id": group["brief_doc_id"]}

    return await asyncio.to_thread(_run)

# ── Group calendar — availability + meetings (phase 3b) ─────────────────
#
# Gated by the asker's `can_query_calendar` permission. Members whose
# Google isn't connected are flagged `has_calendar: false` and excluded
# from the common-slot intersection (we never silently treat an unknown
# calendar as "always free").

@router.get("/{group_id}/availability")
async def group_availability(
    group_id: str,
    start: str = Query(..., description="ISO 8601 window start (UTC)"),
    end: str = Query(..., description="ISO 8601 window end (UTC)"),
    duration_minutes: int = Query(default=30, ge=15, le=240),
    tz_offset_minutes: int = Query(default=0, ge=-720, le=840),
    user: dict = Depends(get_current_user),
):
    """
    Return per-member busy blocks + a list of slots where every member
    (with a connected calendar) is free, within business hours of the
    viewer's local timezone.
    """
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])

    perms = _permissions_for_member_row(m)
    if not perms.get("can_query_calendar"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to query calendars in this group.",
        )

    try:
        from agent.group_calendar import (
            _parse_iso_utc,
            aggregate_member_availability,
            find_common_slots,
        )
        win_start = _parse_iso_utc(start)
        win_end = _parse_iso_utc(end)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad start/end timestamps.")

    if win_end <= win_start:
        raise HTTPException(status_code=400, detail="end must be after start.")
    # Cap the window so a single request can't fan out 30 days × N members
    # of `freebusy` lookups. Two weeks is plenty for a "next available
    # slot" UX.
    max_window = (win_end - win_start).total_seconds()
    if max_window > 14 * 86400:
        raise HTTPException(status_code=400, detail="Window can't exceed 14 days.")

    roster = (
        sb.table("persona_group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
    )
    member_uids = [r["user_id"] for r in (roster.data or [])]
    if not member_uids:
        return {"members": [], "common_slots": []}

    personas = (
        sb.table("persona_agents")
        .select("user_id, name")
        .in_("user_id", member_uids)
        .execute()
    )
    name_by_uid = {p["user_id"]: p.get("name") for p in (personas.data or [])}
    member_rows = [
        {"user_id": uid, "display_name": name_by_uid.get(uid) or "Someone"}
        for uid in member_uids
    ]

    availabilities = await aggregate_member_availability(member_rows, win_start, win_end)
    common = find_common_slots(
        availabilities,
        window_start=win_start,
        window_end=win_end,
        duration_minutes=duration_minutes,
        viewer_tz_offset_minutes=tz_offset_minutes,
    )

    # Audit (phase 5): record one event per member whose calendar was
    # actually read (has_calendar=True). Members without a connected
    # calendar aren't recorded — nothing was read, nothing to receipt.
    for av in availabilities:
        if not av.has_calendar:
            continue
        if av.user_id == user["id"]:
            continue  # don't log "I checked my own calendar"
        _log_audit_event(
            sb,
            group_id=group_id,
            affected_user_id=av.user_id,
            actor_user_id=user["id"],
            kind="calendar_queried",
            metadata={
                "window_start": win_start.isoformat(),
                "window_end": win_end.isoformat(),
            },
        )

    return {
        "window": {"start": win_start.isoformat(), "end": win_end.isoformat()},
        "members": [a.to_dict() for a in availabilities],
        "common_slots": [s.to_dict() for s in common],
        "duration_minutes": duration_minutes,
    }

@router.post("/{group_id}/meetings")
async def create_group_meeting(
    group_id: str,
    body: GroupMeetingCreate,
    user: dict = Depends(get_current_user),
):
    """
    Create a calendar event on the asker's calendar with other group
    members as attendees, then post a `system` message to the chat so
    everyone sees the proposal even if Google's invite email is slow.

    Currently single-sided: only the asker's calendar is touched.
    Google handles invitations to the other members via the standard
    attendee flow — they receive an email + a calendar prompt, accept
    or decline through Google's UI, and that state is mirrored back
    into the asker's event.
    """
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])

    perms = _permissions_for_member_row(m)
    if not perms.get("can_query_calendar"):
        # Same gate as availability — booking implies viewing.
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to schedule meetings in this group.",
        )

    g = sb.table("persona_groups").select("name, owner_user_id, archived_at").eq("id", group_id).limit(1).execute()
    if not g.data or g.data[0].get("archived_at"):
        raise HTTPException(status_code=404, detail="Group not found.")
    group_name = g.data[0]["name"]

    # Roster lookup. The asker can optionally narrow attendees via
    # member_user_ids; default is the whole roster minus the asker.
    roster = (
        sb.table("persona_group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
    )
    all_uids = [r["user_id"] for r in (roster.data or [])]
    if body.member_user_ids:
        target_uids = [u for u in body.member_user_ids if u in all_uids and u != user["id"]]
    else:
        target_uids = [u for u in all_uids if u != user["id"]]

    # Resolve emails for invitees (Supabase admin API; same pattern used
    # in mcp/tools/zynd_network.py:_build_avatar_map).
    attendee_emails: list[str] = []
    if target_uids:
        attendee_emails = await asyncio.to_thread(_fetch_user_emails, target_uids)

    def _run() -> dict:
        from mcp.tools.google.calendar import create_event
        attendees_payload = [{"email": e} for e in attendee_emails if e]
        # The calendar tool's `create_event` doesn't accept attendees
        # directly — patch through with a thin wrapper call.
        result = _create_event_with_attendees(
            user_id=user["id"],
            summary=body.title,
            start_time=body.start,
            end_time=body.end,
            description=body.description or f"Proposed in group: {group_name}",
            location=body.location or "",
            time_zone=body.time_zone or "UTC",
            attendees=attendees_payload,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "Couldn't create the calendar event.",
            )

        # Persist a system-channel message so the group sees the proposal.
        ev = result.get("event") or {}
        meta = {
            "kind": "group_meeting_proposal",
            "event_id": ev.get("id"),
            "title": body.title,
            "start": body.start,
            "end": body.end,
            "location": body.location or None,
            "html_link": ev.get("htmlLink"),
            "attendee_count": len(attendees_payload),
            "proposed_by": user["id"],
        }
        line = (
            f"{_resolve_display_name(user)} proposed a meeting: "
            f"{body.title} — {body.start} → {body.end}."
        )
        if attendees_payload:
            line += f" Invites sent to {len(attendees_payload)} member(s) — check your inbox to RSVP."
        sb.table("persona_group_messages").insert({
            "group_id": group_id,
            "sender_user_id": user["id"],
            "sender_agent_id": m.get("agent_id"),
            "sender_name": _resolve_display_name(user),
            "channel": "system",
            "content": line,
            "metadata": meta,
        }).execute()
        sb.table("persona_groups").update({
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
        return {"status": "ok", "event": ev, "attendee_count": len(attendees_payload)}

    return await asyncio.to_thread(_run)

def _fetch_user_emails(user_ids: list[str]) -> list[str]:
    """Resolve auth.users.email for a list of user_ids via Supabase admin."""
    import requests
    out: list[str] = []
    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    }
    for uid in user_ids:
        try:
            r = requests.get(
                f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{uid}",
                headers=headers,
                timeout=4,
            )
            if not r.ok:
                continue
            user_row = (r.json() or {}).get("user") if isinstance(r.json(), dict) else None
            payload = user_row or (r.json() or {})
            email = (
                payload.get("email")
                or (payload.get("user_metadata") or {}).get("email")
            )
            if isinstance(email, str) and email:
                out.append(email)
        except Exception:
            continue
    return out

def _create_event_with_attendees(
    *,
    user_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str,
    location: str,
    time_zone: str,
    attendees: list[dict],
) -> dict:
    """
    Build a Calendar event with attendees. The existing create_event in
    mcp/tools/google/calendar.py doesn't expose the attendees field, so
    we use the same _get_service() and emit a slightly richer body.

    Returns {success, event} or {success: False, error}.
    """
    try:
        from mcp.tools.google.calendar import _get_service, _parse_iso
        from datetime import timedelta as _td
        service = _get_service(user_id)
        start_dt = _parse_iso(start_time)
        end_dt = _parse_iso(end_time) if end_time else (start_dt + _td(hours=1))
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": time_zone or "UTC"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": time_zone or "UTC"},
            "attendees": attendees,
            "guestsCanSeeOtherGuests": True,
        }
        event = service.events().insert(
            calendarId="primary",
            body=body,
            sendUpdates="all",
        ).execute()
        return {"success": True, "event": event}
    except Exception as e:
        logger.exception(f"[group-meetings] create_event failed: {e}")
        return {"success": False, "error": str(e)}

# ── Group memory — shared constraints (phase 4) ─────────────────────────
# Three kinds:
#   fact  — positive context ("Our launch is May 20")
#   rule  — negative instruction ("Don't quote pricing externally")
#   voice — style guidance ("Warm tone, no exclamation marks")
#
# Read: any member. Write: owner/admin. Member personas see the list
# injected into their dispatch prefix so the constraints apply at
# generation time, not as a post-hoc filter.

@router.get("/{group_id}/constraints")
async def list_constraints(group_id: str, user: dict = Depends(get_current_user)):
    sb = _supabase()
    _require_member(sb, group_id, user["id"])
    try:
        rows = (
            sb.table("persona_group_constraints")
            .select("id, kind, text, created_by_user_id, created_at")
            .eq("group_id", group_id)
            .is_("archived_at", "null")
            .order("created_at")
            .execute()
        )
    except APIError as e:
        if _is_missing_table(e):
            return {"constraints": []}
        raise
    return {"constraints": rows.data or []}

@router.post("/{group_id}/constraints")
async def add_constraint(
    group_id: str,
    body: GroupConstraintCreate,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner", "admin"))

    counts = (
        sb.table("persona_group_constraints")
        .select("id", count="exact")
        .eq("group_id", group_id)
        .is_("archived_at", "null")
        .execute()
    )
    current = getattr(counts, "count", None) or len(counts.data or [])
    if current >= MAX_CONSTRAINTS_PER_GROUP:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This group already has {MAX_CONSTRAINTS_PER_GROUP} constraints. "
                "Remove one before adding another — short, sharp rules outperform long lists."
            ),
        )

    inserted = (
        sb.table("persona_group_constraints")
        .insert({
            "group_id": group_id,
            "kind": body.kind,
            "text": body.text.strip(),
            "created_by_user_id": user["id"],
        })
        .execute()
    )
    sb.table("persona_groups").update({
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", group_id).execute()
    return {"constraint": inserted.data[0] if inserted.data else None}

@router.patch("/{group_id}/constraints/{constraint_id}")
async def update_constraint(
    group_id: str,
    constraint_id: str,
    body: GroupConstraintUpdate,
    user: dict = Depends(get_current_user),
):
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner", "admin"))

    patch: dict = {}
    if body.kind is not None:
        patch["kind"] = body.kind
    if body.text is not None:
        patch["text"] = body.text.strip()
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    r = (
        sb.table("persona_group_constraints")
        .update(patch)
        .eq("id", constraint_id)
        .eq("group_id", group_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(status_code=404, detail="Constraint not found.")
    return {"constraint": r.data[0]}

@router.delete("/{group_id}/constraints/{constraint_id}")
async def archive_constraint(
    group_id: str,
    constraint_id: str,
    user: dict = Depends(get_current_user),
):
    """Soft-delete via archived_at so removed rules stay queryable for audit."""
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])
    _require_role(m, ("owner", "admin"))
    sb.table("persona_group_constraints").update({
        "archived_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", constraint_id).eq("group_id", group_id).execute()
    return {"status": "archived"}

# ── Audit logger (phase 5) ──────────────────────────────────────────────
# Records access events so members can see who looked at what. Best-effort:
# failures are swallowed so a missing audit table never breaks the actual
# dispatch path.

def _log_audit_event(
    sb,
    *,
    group_id: str,
    affected_user_id: str,
    actor_user_id: str | None,
    kind: str,
    metadata: dict | None = None,
) -> None:
    try:
        sb.table("persona_group_audit_events").insert({
            "group_id": group_id,
            "affected_user_id": affected_user_id,
            "actor_user_id": actor_user_id,
            "kind": kind,
            "metadata": metadata,
        }).execute()
    except APIError as e:
        if not _is_missing_table(e):
            logger.warning(f"[group-audit] couldn't log {kind} for {affected_user_id}: {e}")
    except Exception as e:
        logger.warning(f"[group-audit] couldn't log {kind} for {affected_user_id}: {e}")

# ── Audit (phase 5) ────────────────────────────────────────────────────
@router.get("/{group_id}/activity")
async def group_activity(
    group_id: str,
    scope: str = Query(default="me", pattern="^(me|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """
    Return audit events for the caller's data in this group ("me", the
    default — every member can read their own receipts), or for the whole
    group ("all", owner/admin only).
    """
    sb = _supabase()
    m = _require_member(sb, group_id, user["id"])

    if scope == "all":
        _require_role(m, ("owner", "admin"))

    try:
        q = (
            sb.table("persona_group_audit_events")
            .select("id, kind, affected_user_id, actor_user_id, metadata, created_at")
            .eq("group_id", group_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if scope == "me":
            q = q.eq("affected_user_id", user["id"])
        rows = q.execute()
    except APIError as e:
        if _is_missing_table(e):
            return {"events": []}
        raise

    events = rows.data or []
    if not events:
        return {"events": []}

    # Hydrate actor and affected display names so the UI doesn't need a
    # second per-row lookup. Persona name when available; falls back to
    # something readable rather than a UUID.
    uids = {e["actor_user_id"] for e in events if e.get("actor_user_id")}
    uids |= {e["affected_user_id"] for e in events if e.get("affected_user_id")}
    if uids:
        personas = (
            sb.table("persona_agents")
            .select("user_id, name")
            .in_("user_id", list(uids))
            .execute()
        )
        name_by_uid = {p["user_id"]: p.get("name") for p in (personas.data or [])}
    else:
        name_by_uid = {}

    for ev in events:
        ev["actor_name"] = name_by_uid.get(ev.get("actor_user_id")) or "Someone"
        ev["affected_name"] = name_by_uid.get(ev.get("affected_user_id")) or "Someone"
    return {"events": events}
