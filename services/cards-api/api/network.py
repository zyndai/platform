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
from uuid import UUID

import jwt
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import config
from api.auth import Principal, verify_supabase_jwt
from services import network

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


class InvitationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(accept|decline)$")


class ReadMark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(dm|group)$")
    id: UUID
    seq: int = Field(ge=0)


def _uid(authorization: str | None, zynd_user: str | None) -> str:
    return _principal(authorization, zynd_user).sub


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
    return network.send_group_message(
        _uid(authorization, x_zynd_user), str(group_id), body.content,
        str(body.client_id) if body.client_id else None,
    )
