"""Cards-native social graph API.

The caller is always a verified aafo account with a claimed, published Card.
The same endpoints are used by Cards web and the authenticated Cards MCP
bridge; MCP service calls identify the account with X-Zynd-User.

These handlers are deliberately synchronous (`def`, not `async def`). The
Supabase Python client is synchronous, so FastAPI must run these calls in its
threadpool; running them on the event loop blocks every other request in the
single-worker cards-api process.
"""

import hmac
import logging
import re
from uuid import UUID

import jwt
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import config
from api.auth import Principal, verify_supabase_jwt
from services import connection_brief, group_memory, invites, match_prefs, network, saved_searches, trust

_MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_.-]{1,64})")
logger = logging.getLogger(__name__)

router = APIRouter()


def _principal(authorization: str | None, zynd_user: str | None = None) -> Principal:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if config.MEMORY_SERVICE_TOKEN and hmac.compare_digest(token.encode(), config.MEMORY_SERVICE_TOKEN.encode()):
        try:
            uid = str(UUID(zynd_user or ""))
        except ValueError as exc:
            raise HTTPException(401, "Invalid service user identity") from exc
        return Principal(email="", sub=uid, iss=config.AAFO_ISSUER)

    principal = verify_supabase_jwt(authorization)
    if not principal or not config.AAFO_ISSUER or principal.iss != config.AAFO_ISSUER:
        raise HTTPException(403, "Use your shared Zynd account for Cards networking")
    try:
        UUID(principal.sub)
    except ValueError as exc:
        raise HTTPException(403, "Invalid account identity") from exc
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid account session") from exc
    if claims.get("role") not in (None, "authenticated") or claims.get("aud") not in (None, "authenticated"):
        raise HTTPException(403, "Cards networking requires a user session")
    return principal


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_handle: str = Field(min_length=1, max_length=128)
    message: str | None = Field(default=None, max_length=2000)


class ConnectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern="^(accept|decline|block|revoke)$")


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)
    # Client-generated idempotency key. Retrying the same logical send must
    # return the stored row instead of creating a duplicate.
    client_id: UUID | None = None


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    visibility: str = Field(default="private", pattern="^(private|open)$")


class GroupInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_handle: str = Field(min_length=1, max_length=128)
    message: str | None = Field(default=None, max_length=500)


class InviteCreate(BaseModel):
    """Prepared by Memory from its own LinkedIn search result and sent with the service token."""
    model_config = ConfigDict(extra="forbid")
    linkedin_url: str = Field(min_length=10, max_length=300)
    name: str = Field(min_length=1, max_length=120)
    headline: str = Field(default="", max_length=200)
    message: str | None = Field(default=None, max_length=500)


class SavedSearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=100)
    location: str = Field(default="", max_length=100)
    skills: str = Field(default="", max_length=200)
    label: str = Field(default="", max_length=80)


class PreferenceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(hide_person|mute_topic|less_like_this)$")
    value: str = Field(min_length=1, max_length=100)


class CardReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(pattern="^(spam|impersonation|harassment|inaccurate|other)$")
    details: str = Field(default="", max_length=1000)


class InvitationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(accept|decline)$")


class ReadMark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(dm|group)$")
    id: UUID
    seq: int = Field(ge=0)


class GroupMemoryRemember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID | None = None
    content: str | None = Field(default=None, max_length=4000)


class AgentPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def _uid(authorization: str | None, zynd_user: str | None) -> str:
    return _principal(authorization, zynd_user).sub


def _enqueue_group_mentions(user_id: str, group_id: str, result: dict) -> None:
    """Queue Card assistant replies for @handles; never fail the message send."""
    if not config.FEATURE_GROUP_AGENT_REPLIES:
        return
    message = result.get("message") or {}
    content = message.get("content") or ""
    handles = list(dict.fromkeys(match.lower() for match in _MENTION_RE.findall(content)))
    if not handles:
        result["agent_replies"] = 0
        return
    try:
        members = group_memory.members(group_id)
        by_handle = {
            (member.get("handle") or "").lower(): member["user_id"]
            for member in members
            if member.get("handle") and member.get("user_id")
        }
        mentioned = []
        for handle in handles:
            target = by_handle.get(handle)
            if target and target != user_id and target not in mentioned:
                mentioned.append(target)
        mentioned = mentioned[:2]
        if not mentioned:
            result["agent_replies"] = 0
            return
        queued = group_memory.enqueue_agent_replies(str(message["id"]), mentioned)
        result["agent_replies"] = int(queued.get("enqueued") or 0)
        # The mention list is metadata for the message page; the content stays
        # untouched so the UI can render @handles in the accent colour.
        try:
            config.get_supabase().table("group_messages").update({"mentions": mentioned}).eq("id", message["id"]).execute()
            message["mentions"] = mentioned
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001 — sending must not depend on the queue
        logger.warning("could not queue group mentions: %s", exc)
        result["agent_replies"] = 0


@router.get("/network/inbox")
def inbox(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.get_inbox(_uid(authorization, x_zynd_user))


@router.get("/network/connections")
def connections(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.list_connections(_uid(authorization, x_zynd_user))


@router.post("/network/connections")
def request_connection(body: ConnectionCreate, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.request_connection(_uid(authorization, x_zynd_user), body.target_handle, body.message)


@router.post("/network/connections/{connection_id}/respond")
def respond_connection(connection_id: UUID, body: ConnectionDecision, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.respond_connection(_uid(authorization, x_zynd_user), str(connection_id), body.action)


@router.get("/network/connections/{connection_id}/messages")
def connection_messages(
    connection_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    before_seq: int | None = Query(default=None, ge=0),
    after_seq: int | None = Query(default=None, ge=0),
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    return network.list_messages(
        _uid(authorization, x_zynd_user), str(connection_id), limit, before_seq, after_seq,
    )


@router.post("/network/connections/{connection_id}/messages")
def send_connection_message(connection_id: UUID, body: MessageCreate, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.send_message(
        _uid(authorization, x_zynd_user), str(connection_id), body.content,
        str(body.client_id) if body.client_id else None,
    )


@router.post("/network/read")
def mark_read(body: ReadMark, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.mark_read(_uid(authorization, x_zynd_user), body.kind, str(body.id), body.seq)


@router.get("/network/groups")
def groups(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.list_groups(_uid(authorization, x_zynd_user))


@router.post("/network/groups")
def create_group(body: GroupCreate, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.create_group(_uid(authorization, x_zynd_user), body.name, body.description, body.visibility)


@router.get("/network/groups/{group_id}/members")
def group_members(group_id: UUID, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.list_members(_uid(authorization, x_zynd_user), str(group_id))


@router.get("/network/groups/{group_id}/people")
def group_people(group_id: UUID, query: str = Query("", max_length=120), authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.search_invitable(_uid(authorization, x_zynd_user), str(group_id), query)


@router.post("/network/groups/{group_id}/invitations")
def invite_group_member(group_id: UUID, body: GroupInvite, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    user_id = _uid(authorization, x_zynd_user)
    target = network._card_for_handle(body.target_handle)
    return network.invite_to_group(user_id, str(group_id), target["owner_user_id"], body.message)


@router.get("/network/groups/{group_id}/invitations")
def group_invitations(group_id: UUID, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.list_invitations(_uid(authorization, x_zynd_user), str(group_id))


@router.get("/network/group-invitations")
def incoming_group_invitations(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.list_incoming_invitations(_uid(authorization, x_zynd_user))


@router.post("/network/group-invitations/{invitation_id}/respond")
def respond_group_invitation(invitation_id: UUID, body: InvitationDecision, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return network.respond_invitation(_uid(authorization, x_zynd_user), str(invitation_id), body.decision)


@router.get("/network/groups/{group_id}/messages")
def group_messages(
    group_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    before_seq: int | None = Query(default=None, ge=0),
    after_seq: int | None = Query(default=None, ge=0),
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    return network.list_group_messages(
        _uid(authorization, x_zynd_user), str(group_id), limit, before_seq, after_seq,
    )


@router.post("/network/groups/{group_id}/messages")
def send_group_message(group_id: UUID, body: MessageCreate, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    user_id = _uid(authorization, x_zynd_user)
    result = network.send_group_message(
        user_id, str(group_id), body.content,
        str(body.client_id) if body.client_id else None,
    )
    if not result.get("duplicate"):
        _enqueue_group_mentions(user_id, str(group_id), result)
    return result


@router.get("/network/groups/{group_id}/memory")
def group_memory_list(
    group_id: UUID,
    q: str = Query("", max_length=300),
    limit: int = Query(30, ge=1, le=100),
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    if not config.FEATURE_GROUP_MEMORY:
        raise HTTPException(503, "Group memory is not enabled")
    user_id = _uid(authorization, x_zynd_user)
    if q.strip():
        return group_memory.search_memory(
            user_id, str(group_id), q, min(limit, config.GROUP_MEMORY_SEARCH_LIMIT),
        )
    return group_memory.list_memory(user_id, str(group_id), limit)


@router.post("/network/groups/{group_id}/memory")
def group_memory_write(
    group_id: UUID,
    body: GroupMemoryRemember,
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    if not config.FEATURE_GROUP_MEMORY:
        raise HTTPException(503, "Group memory is not enabled")
    user_id = _uid(authorization, x_zynd_user)
    if body.message_id is not None:
        return group_memory.remember_message(user_id, str(group_id), str(body.message_id))
    if body.content is not None:
        return group_memory.add_fact(user_id, str(group_id), body.content)
    raise HTTPException(422, "Send a message_id or content")


@router.get("/network/agent-preferences")
def agent_preferences(
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    return group_memory.get_agent_preference(_uid(authorization, x_zynd_user))


@router.put("/network/agent-preferences")
def update_agent_preferences(
    body: AgentPreferenceUpdate,
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    return group_memory.set_agent_preference(_uid(authorization, x_zynd_user), body.enabled)


@router.post("/network/invites")
async def create_invite(body: InviteCreate, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    """Invite someone with no claimed Card. Only Memory (service token) may supply the name and
    headline, because they are published on the new Card; a browser session cannot."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not (config.MEMORY_SERVICE_TOKEN and hmac.compare_digest(token.encode(), config.MEMORY_SERVICE_TOKEN.encode())):
        raise HTTPException(403, "Invitations are prepared by the Zynd assistant, not the browser")
    return invites.create_invite(
        _uid(authorization, x_zynd_user), linkedin_url=body.linkedin_url, name=body.name,
        headline=body.headline, message=body.message or "")


@router.get("/network/invites")
async def list_invites(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return invites.list_invites(_uid(authorization, x_zynd_user))


@router.post("/network/invites/{invite_id}/cancel")
async def cancel_invite(invite_id: UUID, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return invites.cancel_invite(_uid(authorization, x_zynd_user), str(invite_id))


@router.get("/network/connections/{connection_id}/brief")
async def connection_brief_route(connection_id: UUID, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    """A5: what each person is working on now, shared ground and topics. Accepted connections only."""
    return network.connection_brief(_uid(authorization, x_zynd_user), str(connection_id))


@router.get("/network/groups/{group_id}/search")
async def search_group(
    group_id: UUID, q: str = Query("", max_length=200), role: str = Query("", max_length=100),
    location: str = Query("", max_length=100), skills: str = Query("", max_length=200),
    limit: int = Query(10, ge=1, le=50),
    authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None),
):
    """A7: search only the Cards of one group's members. Members only."""
    return network.search_group(_uid(authorization, x_zynd_user), str(group_id), q=q, role=role,
                                location=location, skills=skills, limit=limit)


@router.post("/network/saved-searches")
async def add_saved_search(body: SavedSearchCreate, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return saved_searches.add(_uid(authorization, x_zynd_user), q=body.q, role=body.role, location=body.location,
                              skills=body.skills, label=body.label)


@router.get("/network/saved-searches")
async def list_saved_searches(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return saved_searches.list_searches(_uid(authorization, x_zynd_user))


@router.delete("/network/saved-searches/{search_id}")
async def remove_saved_search(search_id: UUID, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return saved_searches.remove(_uid(authorization, x_zynd_user), str(search_id))


@router.get("/network/preferences")
async def get_preferences(authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return {"preferences": match_prefs.get(_uid(authorization, x_zynd_user))}


@router.post("/network/preferences")
async def add_preference(body: PreferenceChange, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return match_prefs.add(_uid(authorization, x_zynd_user), body.kind, body.value)


@router.post("/network/preferences/remove")
async def remove_preference(body: PreferenceChange, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return match_prefs.remove(_uid(authorization, x_zynd_user), body.kind, body.value)


@router.post("/network/cards/{handle}/report")
async def report_card(handle: str, body: CardReport, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return trust.report_card(_uid(authorization, x_zynd_user), handle, body.reason, body.details)


@router.post("/network/cards/{handle}/block")
async def block_card(handle: str, authorization: str | None = Header(default=None), x_zynd_user: str | None = Header(default=None)):
    return trust.block_card(_uid(authorization, x_zynd_user), handle)
