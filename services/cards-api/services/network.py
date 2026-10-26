"""Cards-native connections, direct messages, and groups.

Cards is the source of truth for this social graph. The service-role client is
used deliberately: browser callers authenticate with a shared Supabase session
and this module enforces every ownership, acceptance, and membership check
before writing the Cards schema.

Messaging v2 is implemented as service-only Postgres functions so a page load,
message page, send, or read receipt is one Supabase round trip instead of a
chain of REST calls. The database functions also assign the per-conversation
sequence and keep inbox summaries/read cursors consistent for every writer.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import HTTPException

import config

logger = logging.getLogger(__name__)


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


def _find_card_for_user(user_id: str) -> dict | None:
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
    return rows[0] if rows else None


def _card_for_user(user_id: str) -> dict:
    card = _find_card_for_user(user_id)
    if not card:
        raise HTTPException(409, "You need a claimed, published Card before using Connections")
    return card


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
    if not cards:
        return {"card_id": partner_id, "name": "Zynd member"}
    payload = _card_payload(cards[0])
    if row.get("status") == "accepted":
        # Contact links are for people who have agreed to connect: search results never carry
        # them, and neither does a pending request.
        links = ((cards[0].get("card") or {}).get("identity") or {}).get("links") or {}
        payload["links"] = {k: v for k, v in links.items() if isinstance(v, str) and v.strip()}
    return payload


def _serialize_connection(row: dict, user_id: str) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "incoming": row["recipient_user_id"] == user_id,
        "created_at": row.get("created_at"),
        "decided_at": row.get("decided_at"),
        "updated_at": row.get("updated_at"),
        "request_message": row.get("request_message"),
        "partner": _partner_card(row, user_id),
    }


def _rpc_result(name: str, params: dict) -> dict:
    result = _sb().rpc(name, params).execute().data
    if not isinstance(result, dict):
        raise HTTPException(500, "Cards network operation failed")
    if result.get("error"):
        raise HTTPException(result.get("status_code", 409), result["error"])
    return result


def _create_connection(
    requester_user_id: str, requester: dict, recipient_user_id: str, recipient: dict, message: str | None,
    before_insert=None,
) -> tuple[dict, bool]:
    """The one place a connection request is written: (row, already_existed).

    One row per pair of people (connection_key), whoever asked first; a second request,
    in either direction, returns the existing row instead of a duplicate.
    """
    key = _connection_key(requester_user_id, recipient_user_id)
    existing = _sb().table("connections").select("*").eq("connection_key", key).limit(1).execute().data or []
    if existing:
        return existing[0], True
    if before_insert is not None:
        before_insert()      # limits apply to NEW requests only; repeating one is harmless
    try:
        inserted = _sb().table("connections").insert({
            "connection_key": key,
            "requester_user_id": requester_user_id,
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
                return existing[0], True
        raise
    if not inserted.data:
        raise HTTPException(500, "Could not create connection request")
    return inserted.data[0], False


def request_connection(user_id: str, target_handle: str, message: str | None = None) -> dict:
    requester = _card_for_user(user_id)
    recipient = _card_for_handle(target_handle)
    recipient_user_id = recipient["owner_user_id"]
    if recipient_user_id == user_id:
        raise HTTPException(422, "You cannot connect to your own Card")
    from services import trust
    row, existed = _create_connection(
        user_id, requester, recipient_user_id, recipient, message,
        before_insert=lambda: trust.check_request_limits(user_id, recipient_user_id))
    if not existed:
        from services import suggestions
        suggestions.mark_connected(requester.get("id"), recipient.get("id"))
    return {"connection": _serialize_connection(row, user_id), "existing": existed}


# Characters that mean something inside a PostgREST or() filter (separators, grouping, wildcards,
# the operator colon, quoting) plus control characters. A search box must never be able to reshape
# the filter it lands in.
_FILTER_SYNTAX = re.compile(r'[,()*%:"\\\x00-\x1f\x7f]')
SUGGEST_MIN_CHARS = 2
SUGGEST_FETCH = 25


def _search_term(query: str) -> str:
    """Typed text made safe to embed in a PostgREST or() filter: syntax characters and a leading @
    are dropped, whitespace is collapsed, and the length is capped."""
    term = " ".join(_FILTER_SYNTAX.sub(" ", query or "").split())
    return term.lstrip("@ ")[:64]


def _suggest_rank(row: dict, needle: str) -> int:
    """0: the handle starts with the text; 1: the name (or any word in it) does; 2: it is elsewhere."""
    handle = (row.get("handle") or "").lower()
    name = (((row.get("card") or {}).get("identity") or {}).get("name") or "").lower()
    if handle.startswith(needle):
        return 0
    if name.startswith(needle) or any(word.startswith(needle) for word in re.split(r"[\s._-]+", name)):
        return 1
    return 2


def _connection_summary(row: dict, user_id: str) -> dict:
    return {"id": row["id"], "status": row["status"], "incoming": row.get("recipient_user_id") == user_id}


def suggest_people(user_id: str, query: str, limit: int = 8) -> dict:
    """Typeahead for "who do you want to connect with": claimed, published Cards whose handle or
    name contains the text, best matches first, each with the caller's existing connection (if any)
    so the UI can offer Message / show Requested instead of a send that cannot succeed.

    Public Card data only: no owner email and no contact links (those are for accepted connections)."""
    term = _search_term(query)
    if len(term) < SUGGEST_MIN_CHARS:
        return {"people": []}
    # Quoted so spaces and dots in a name survive; the term holds no quote or backslash to escape.
    # `*` is PostgREST's URL-safe LIKE wildcard. A literal `_` in the text still acts as a one-char
    # wildcard, which only widens the DB match (the ranking below puts real matches first).
    pattern = f'"*{term}*"'
    rows = (
        _sb()
        .table("agent_profile_cards")
        .select("id,handle,card,owner_user_id")
        .eq("status", "published")
        .not_.is_("owner_email", "null")
        .not_.is_("owner_user_id", "null")
        .or_(f"handle.ilike.{pattern},card->identity->>name.ilike.{pattern}")
        .order("published_at", desc=True, nullsfirst=False)
        .limit(SUGGEST_FETCH)
        .execute()
        .data
        or []
    )
    needle = term.lower()
    ranked = sorted(enumerate(rows), key=lambda item: (_suggest_rank(item[1], needle), item[0]))
    picked: list[dict] = []
    seen: set[str] = set()
    for _, row in ranked:
        owner = row.get("owner_user_id")
        if not owner or owner == user_id or owner in seen:
            continue    # one entry per person, and never the caller
        seen.add(owner)
        picked.append(row)
        if len(picked) >= max(1, min(limit, SUGGEST_FETCH)):
            break
    if not picked:
        return {"people": []}

    keys = {row["owner_user_id"]: _connection_key(user_id, row["owner_user_id"]) for row in picked}
    connections = (
        _sb()
        .table("connections")
        .select("id,status,connection_key,requester_user_id,recipient_user_id")
        .in_("connection_key", list(keys.values()))
        .execute()
        .data
        or []
    )
    by_key = {c["connection_key"]: c for c in connections}
    return {"people": [
        {
            **_card_payload(row),
            "connection": (
                _connection_summary(by_key[keys[row["owner_user_id"]]], user_id)
                if keys[row["owner_user_id"]] in by_key else None
            ),
        }
        for row in picked
    ]}


def _connect_blocker(connection: dict | None, has_card: bool) -> str | None:
    """Why a new request cannot be sent, or None when one can.

    A connection row is per pair of people and final once decided: _create_connection returns the
    existing row whatever its status, and respond_connection only moves a row out of `pending`.
    So declined, revoked and blocked can never become a fresh request, and the UI must not offer
    one. Blocked is worded neutrally: it does not say who blocked whom."""
    if connection:
        status = connection["status"]
        if status == "accepted":
            return "You are already connected."
        if status == "pending":
            return "They already sent you a request." if connection["incoming"] else "Your request is waiting for their answer."
        if status == "declined":
            return "You declined this request." if connection["incoming"] else "This request was not accepted."
        if status == "revoked":
            return "This connection was ended."
        return "Connecting with this person is not available."
    if not has_card:
        return "Claim and publish your own Card to connect with people."
    return None


def connection_status(user_id: str, handle: str) -> dict:
    """Where the caller stands with one Card, for the profile page's Connect / Message button.

    Only reports state: a caller without a Card of their own gets can_connect=false, not the 409
    that request_connection raises."""
    target = _card_for_handle(handle)
    other = target["owner_user_id"]
    if other == user_id:
        return {"self": True}
    rows = (
        _sb()
        .table("connections")
        .select("id,status,connection_key,requester_user_id,recipient_user_id")
        .eq("connection_key", _connection_key(user_id, other))
        .limit(1)
        .execute()
        .data
        or []
    )
    connection = _connection_summary(rows[0], user_id) if rows else None
    # An existing connection already settles the answer; only look up the caller's own Card without one.
    reason = _connect_blocker(connection, has_card=bool(connection) or bool(_find_card_for_user(user_id)))
    return {"connection": connection, "can_connect": reason is None, "reason": reason}


def get_inbox(user_id: str) -> dict:
    """One round trip: connections, groups, invitations, summaries, unread."""
    return _rpc_result("network_inbox", {"p_user": user_id})


def list_connections(user_id: str) -> dict:
    from services import invites
    invites.deliver_for_user(user_id)    # invitations that were waiting for their Card to be claimed
    connections = get_inbox(user_id).get("connections", [])
    return {"connections": _with_accepted_links(connections)}


def _with_accepted_links(connections: list[dict]) -> list[dict]:
    """Contact links are for people who have agreed to connect: the inbox carries the partner's
    public identity only, so add the owner's chosen links for ACCEPTED connections (never for pending,
    declined or blocked ones, and never in search results)."""
    ids = [c["partner"]["card_id"] for c in connections
           if c.get("status") == "accepted" and (c.get("partner") or {}).get("card_id")]
    if not ids:
        return connections
    rows = _sb().table("agent_profile_cards").select("id,card").in_("id", ids).execute().data or []
    links_by_id = {
        r["id"]: {k: v for k, v in (((r.get("card") or {}).get("identity") or {}).get("links") or {}).items()
                  if isinstance(v, str) and v.strip()}
        for r in rows
    }
    for c in connections:
        partner = c.get("partner") or {}
        if c.get("status") == "accepted" and partner.get("card_id") in links_by_id:
            partner["links"] = links_by_id[partner["card_id"]]
    return connections


def connection_brief(user_id: str, connection_id: str) -> dict:
    """A5: what each side is doing now, what they share and what to talk about, for an accepted
    connection only (a pending or blocked one reveals nothing beyond the public Card)."""
    from models.card import AgentProfileCard
    from services import connection_brief as brief

    row = _connection_row(connection_id)
    _require_connection_party(row, user_id)
    if row.get("status") != "accepted":
        raise HTTPException(409, "Accept the connection first")
    mine_id, theirs_id = (row["requester_card_id"], row["recipient_card_id"]) if row["requester_user_id"] == user_id \
        else (row["recipient_card_id"], row["requester_card_id"])
    cards = _sb().table("agent_profile_cards").select("id,handle,card").in_("id", [mine_id, theirs_id]).execute().data or []
    by_id = {c["id"]: c for c in cards}
    if mine_id not in by_id or theirs_id not in by_id:
        raise HTTPException(404, "Connection not found")

    def load(card_row: dict) -> AgentProfileCard:
        card = AgentProfileCard.model_validate(card_row.get("card") or {})
        card.handle = card_row.get("handle") or card.handle
        return card

    return {"connection_id": connection_id, "brief": brief.build_brief(load(by_id[mine_id]), load(by_id[theirs_id]))}


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


def list_messages(
    user_id: str,
    connection_id: str,
    limit: int = 100,
    before_seq: int | None = None,
    after_seq: int | None = None,
) -> dict:
    return _rpc_result("network_dm_messages", {
        "p_user": user_id,
        "p_connection": connection_id,
        "p_before_seq": before_seq,
        "p_after_seq": after_seq,
        "p_limit": max(1, min(limit, 500)),
    })


def send_message(
    user_id: str,
    connection_id: str,
    content: str,
    client_id: str | None = None,
) -> dict:
    return _rpc_result("network_send_dm", {
        "p_user": user_id,
        "p_connection": connection_id,
        "p_client_id": client_id,
        "p_content": content,
    })


def mark_read(user_id: str, kind: str, target_id: str, seq: int) -> dict:
    return _rpc_result("network_mark_read", {
        "p_user": user_id,
        "p_kind": kind,
        "p_id": target_id,
        "p_seq": max(0, seq),
    })


def _group(group_id: str) -> dict:
    rows = _sb().table("groups").select("*").eq("id", group_id).is_("archived_at", "null").limit(1).execute().data or []
    if not rows:
        raise HTTPException(404, "Group not found")
    return rows[0]


def _member(group_id: str, user_id: str) -> dict | None:
    rows = _sb().table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def _require_member(group_id: str, user_id: str) -> dict:
    _group(group_id)
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
    return _rpc_result("network_create_group", {
        "p_user": user_id, "p_name": clean_name[:80],
        "p_description": (description or "").strip()[:500] or None,
        "p_visibility": visibility,
    })


def list_groups(user_id: str) -> dict:
    return {"groups": get_inbox(user_id).get("groups", [])}


def list_members(user_id: str, group_id: str) -> dict:
    return _rpc_result("network_group_members", {"p_user": user_id, "p_group": group_id})


def _require_owner(user_id: str, group_id: str) -> dict:
    member = _require_member(group_id, user_id)
    if member.get("role") != "owner":
        raise HTTPException(403, "Only the group owner can do that")
    return member


def update_group(user_id: str, group_id: str, name: str | None, description: str | None) -> dict:
    _require_owner(user_id, group_id)
    patch: dict = {"updated_at": _now()}
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(400, "Group name cannot be empty")
        patch["name"] = clean_name[:80]
    if description is not None:
        patch["description"] = description.strip()[:500] or None
    if len(patch) == 1:
        raise HTTPException(400, "Nothing to update")
    rows = _sb().table("groups").update(patch).eq("id", group_id).is_("archived_at", "null").execute().data or []
    if not rows:
        raise HTTPException(404, "Group not found")
    return {"group": rows[0]}


def archive_group(user_id: str, group_id: str) -> dict:
    """Owner deletes a group. Archived rows are hidden from every read path (inbox, members,
    messages), and nothing is erased, so this is recoverable by hand."""
    _require_owner(user_id, group_id)
    _sb().table("groups").update({"archived_at": _now(), "updated_at": _now()}).eq("id", group_id).execute()
    return {"ok": True}


def remove_group_member(user_id: str, group_id: str, member_user_id: str) -> dict:
    _require_owner(user_id, group_id)
    if member_user_id == user_id:
        raise HTTPException(409, "The owner can't be removed. Delete the group instead.")
    target = _member(group_id, member_user_id)
    if not target:
        raise HTTPException(404, "That person is not in this group")
    _sb().table("group_members").delete().eq("group_id", group_id).eq("user_id", member_user_id).execute()
    return {"ok": True}


def leave_group(user_id: str, group_id: str) -> dict:
    member = _require_member(group_id, user_id)
    if member.get("role") == "owner":
        raise HTTPException(409, "Owners can't leave their own group. Delete the group instead.")
    _sb().table("group_members").delete().eq("group_id", group_id).eq("user_id", user_id).execute()
    return {"ok": True}


def search_group(user_id: str, group_id: str, *, q: str = "", role: str = "", location: str = "",
                 skills: str = "", limit: int = 10, topics: str = "",
                 relax: bool = False) -> dict:
    """A7: people search scoped to one group (an event, a community). Only members can ask, only
    the group's own Cards are searched, and the caller never finds themselves."""
    from models.card import AgentProfileCard
    from services import search as search_service
    from services import trust

    _require_member(group_id, user_id)
    member_ids = [m["user_id"] for m in (_sb().table("group_members").select("user_id").eq("group_id", group_id).execute().data or [])]
    rows = (_sb().table("agent_profile_cards").select("id,card,handle,owner_user_id,owner_email,embedding")
            .in_("owner_user_id", member_ids).eq("status", "published").execute().data or []) if member_ids else []
    mine = next((r for r in rows if r.get("owner_user_id") == user_id), None)
    rows = [r for r in rows if r.get("owner_user_id") != user_id]
    searcher = None
    if mine is not None:
        searcher = AgentProfileCard.model_validate(mine.get("card") or {})
        searcher.handle = mine.get("handle") or searcher.handle
    results = search_service.search_agents(
        q=q, role=role, location=location, skills=skills, limit=max(1, min(limit, 50)),
        include_unclaimed=True, searcher=searcher, candidate_rows=rows,
        topics=topics, relax=relax)
    verified = trust.verified_by_card_ids([r["agent_id"] for r in results])
    for r in results:
        r["claimed"] = True
        r["verified"] = verified.get(r["agent_id"], [])
    return {"group_id": group_id, "members_searched": len(rows), "results": results}


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
    pending = (_sb().table("group_invitations").select("invitee_user_id")
               .eq("group_id", group_id).eq("status", "pending").gt("expires_at", _now()).execute().data or [])
    excluded.update(row["invitee_user_id"] for row in pending)
    connections = (_sb().table("connections").select("requester_user_id,recipient_user_id")
                   .eq("status", "accepted").or_(f"requester_user_id.eq.{user_id},recipient_user_id.eq.{user_id}")
                   .execute().data or [])
    targets = sorted({
        row["recipient_user_id"] if row["requester_user_id"] == user_id else row["requester_user_id"]
        for row in connections
    } - excluded - {user_id})
    if not targets:
        return {"people": []}
    cards = (_sb().table("agent_profile_cards").select("id,owner_user_id,handle,card")
             .in_("owner_user_id", targets).eq("status", "published").not_.is_("owner_email", "null")
             .execute().data or [])
    results = []
    seen = set()
    for card in cards:
        target = card.get("owner_user_id")
        if not target or target in seen:
            continue
        payload = _card_payload(card)
        haystack = f"{payload.get('handle') or ''} {payload.get('name') or ''} {payload.get('headline') or ''}".lower()
        if query.strip() and query.strip().lower() not in haystack:
            continue
        results.append({**payload, "user_id": target})
        seen.add(target)
    return {"people": results[:100]}


def invite_to_group(user_id: str, group_id: str, invitee_user_id: str, message: str | None) -> dict:
    member = _require_member(group_id, user_id)
    if member.get("role") != "owner":
        raise HTTPException(403, "Only the group owner can invite people")
    _group(group_id)
    if invitee_user_id == user_id or not _connected(user_id, invitee_user_id):
        raise HTTPException(409, "Invitees must be an accepted Card connection")
    if _member(group_id, invitee_user_id):
        raise HTTPException(409, "That Card is already in the group")
    # Expired pending rows must not permanently block a fresh invitation.
    (_sb().table("group_invitations").update({"status": "expired", "decided_at": _now()})
     .eq("group_id", group_id).eq("invitee_user_id", invitee_user_id)
     .eq("status", "pending").lte("expires_at", _now()).execute())
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
    rows = (_sb().table("group_invitations").select("*").eq("group_id", group_id)
            .eq("status", "pending").gt("expires_at", _now()).order("created_at", desc=True).execute().data or [])
    # Show who is being invited, not just their user id. Only public Card fields leave here.
    invitee_ids = list({row["invitee_user_id"] for row in rows})
    cards_by_owner: dict = {}
    if invitee_ids:
        for card in (_sb().table("agent_profile_cards").select("id,handle,card,owner_user_id")
                     .in_("owner_user_id", invitee_ids).eq("status", "published").execute().data or []):
            cards_by_owner.setdefault(card["owner_user_id"], card)
    for row in rows:
        card = cards_by_owner.get(row["invitee_user_id"])
        row["invitee"] = _card_payload(card) if card else None
    return {"invitations": rows}


def cancel_invitation(user_id: str, group_id: str, invitation_id: str) -> dict:
    _require_owner(user_id, group_id)
    rows = (_sb().table("group_invitations").update({"status": "revoked", "decided_at": _now()})
            .eq("id", invitation_id).eq("group_id", group_id).eq("status", "pending").execute().data or [])
    if not rows:
        raise HTTPException(404, "That invitation is no longer pending")
    return {"ok": True}


def transfer_group(user_id: str, group_id: str, new_owner_user_id: str) -> dict:
    """Hand the group to another member. The new owner is promoted first, so a failure midway
    leaves two owners (fixable) rather than none (not fixable from the app)."""
    _require_owner(user_id, group_id)
    if new_owner_user_id == user_id:
        raise HTTPException(400, "You already own this group")
    if not _member(group_id, new_owner_user_id):
        raise HTTPException(404, "That person is not in this group")
    _sb().table("group_members").update({"role": "owner"}).eq("group_id", group_id).eq("user_id", new_owner_user_id).execute()
    _sb().table("groups").update({"owner_user_id": new_owner_user_id, "updated_at": _now()}).eq("id", group_id).execute()
    _sb().table("group_members").update({"role": "member"}).eq("group_id", group_id).eq("user_id", user_id).execute()
    return {"ok": True}


def _preview(content: str) -> str:
    """Same shape the database triggers write to last_message_preview."""
    return " ".join(content.split())[:140]


def _preview_patch(latest: dict | None) -> dict:
    """The inbox preview columns, rewritten to describe the newest message that is left."""
    if not latest:
        return {"last_message_preview": None, "last_message_at": None, "last_message_sender_user_id": None}
    return {
        "last_message_preview": _preview(latest["content"]),
        "last_message_at": latest["created_at"],
        "last_message_sender_user_id": latest["sender_user_id"],
    }


def _announce_deleted(topic: str, message_id: str) -> None:
    """Tell open clients to drop a deleted message. Best effort: the delete has already happened,
    and a client that misses this drops the message on its next refresh."""
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
        return
    key = config.SUPABASE_SERVICE_KEY
    body = {"messages": [{
        "topic": topic,
        "event": "message_deleted",
        "payload": {"message_id": message_id},
        "private": True,
    }]}
    try:
        httpx.post(
            f"{config.SUPABASE_URL.rstrip('/')}/realtime/v1/api/broadcast",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=5.0,
        ).raise_for_status()
    except Exception:  # noqa: BLE001 — delivery is optional
        logger.warning("message_deleted broadcast failed topic=%s", topic, exc_info=True)


def delete_group_message(user_id: str, group_id: str, message_id: str) -> dict:
    """Members delete only their own messages. Replies to it keep their text (the foreign key sets
    reply_to to null), and memory built from it is kept, since it was saved on purpose."""
    _require_member(group_id, user_id)
    rows = (_sb().table("group_messages").select("id,sender_user_id").eq("id", message_id).eq("group_id", group_id)
            .limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Message not found")
    if rows[0]["sender_user_id"] != user_id:
        raise HTTPException(403, "You can only delete your own messages")
    _sb().table("group_messages").delete().eq("id", message_id).execute()
    latest = (_sb().table("group_messages").select("content,created_at,sender_user_id").eq("group_id", group_id)
              .order("created_at", desc=True).limit(1).execute().data or [])
    _sb().table("groups").update(_preview_patch(latest[0] if latest else None)).eq("id", group_id).execute()
    _announce_deleted(f"cards:group:{group_id}", message_id)
    return {"ok": True}


def delete_dm_message(user_id: str, connection_id: str, message_id: str) -> dict:
    row = _connection_row(connection_id)
    _require_connection_party(row, user_id)
    threads = _sb().table("dm_threads").select("id").eq("connection_id", connection_id).limit(1).execute().data or []
    if not threads:
        raise HTTPException(404, "Message not found")
    thread_id = threads[0]["id"]
    rows = (_sb().table("dm_messages").select("id,sender_user_id").eq("id", message_id).eq("thread_id", thread_id)
            .limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Message not found")
    if rows[0]["sender_user_id"] != user_id:
        raise HTTPException(403, "You can only delete your own messages")
    _sb().table("dm_messages").delete().eq("id", message_id).execute()
    latest = (_sb().table("dm_messages").select("content,created_at,sender_user_id").eq("thread_id", thread_id)
              .order("created_at", desc=True).limit(1).execute().data or [])
    _sb().table("dm_threads").update(_preview_patch(latest[0] if latest else None)).eq("id", thread_id).execute()
    _announce_deleted(f"cards:dm:{thread_id}", message_id)
    return {"ok": True}


def list_incoming_invitations(user_id: str) -> dict:
    return {"invitations": get_inbox(user_id).get("invitations", [])}


def respond_invitation(user_id: str, invitation_id: str, decision: str) -> dict:
    if decision not in {"accept", "decline"}:
        raise HTTPException(400, "decision must be accept or decline")
    return _rpc_result("network_respond_invitation", {
        "p_user": user_id, "p_invitation": invitation_id, "p_decision": decision,
    })


def list_group_messages(
    user_id: str,
    group_id: str,
    limit: int = 100,
    before_seq: int | None = None,
    after_seq: int | None = None,
) -> dict:
    return _rpc_result("network_group_messages", {
        "p_user": user_id,
        "p_group": group_id,
        "p_before_seq": before_seq,
        "p_after_seq": after_seq,
        "p_limit": max(1, min(limit, 500)),
    })


def send_group_message(
    user_id: str,
    group_id: str,
    content: str,
    client_id: str | None = None,
) -> dict:
    return _rpc_result("network_send_group_message", {
        "p_user": user_id,
        "p_group": group_id,
        "p_client_id": client_id,
        "p_content": content,
    })
