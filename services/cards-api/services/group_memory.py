"""Per-group durable memory for Cards.

The group conversation is not copied into memory. Agents get the last N
messages as raw context; this module owns the rolling summary, the durable
facts (including messages a member explicitly remembers), and semantic search
over those summaries/facts.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import HTTPException

import config

logger = logging.getLogger(__name__)


def _sb():
    if config.SUPABASE_DB_SCHEMA != "cards":
        raise HTTPException(503, "Group memory requires the shared cards schema")
    return config.get_supabase()


def _rpc_result(name: str, params: dict) -> Any:
    result = _sb().rpc(name, params).execute().data
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(result.get("status_code", 409), result["error"])
    return result


def content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _embed(content: str) -> list[float] | None:
    """Best effort: a missing OpenAI key must not block Remember."""
    try:
        from services.embed import embed_text
        vector = embed_text(content)
        return vector or None
    except Exception as exc:  # noqa: BLE001 — memory still works without embeddings
        logger.warning("group memory embedding failed: %s", exc)
        return None


def _require_member(group_id: str, user_id: str) -> None:
    rows = (
        _sb().table("group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "Group not found")


def group_info(group_id: str) -> dict:
    rows = (
        _sb().table("groups")
        .select("id,name,description,owner_user_id,message_count,created_at")
        .eq("id", group_id)
        .is_("archived_at", "null")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "Group not found")
    return rows[0]


def members(group_id: str) -> list[dict]:
    rows = (
        _sb().table("group_members")
        .select("user_id,role,joined_at")
        .eq("group_id", group_id)
        .execute()
        .data
        or []
    )
    if not rows:
        return []
    ids = [row["user_id"] for row in rows]
    cards = (
        _sb().table("agent_profile_cards")
        .select("owner_user_id,handle,owner_email,card")
        .in_("owner_user_id", ids)
        .eq("status", "published")
        .execute()
        .data
        or []
    )
    by_user = {row["owner_user_id"]: row for row in cards if row.get("owner_user_id")}
    out = []
    for row in rows:
        card = by_user.get(row["user_id"]) or {}
        payload = card.get("card") or {}
        identity = payload.get("identity") or {}
        out.append({
            **row,
            "handle": card.get("handle"),
            "owner_email": card.get("owner_email"),
            "name": identity.get("name") or "Zynd member",
            "headline": identity.get("headline") or "",
            "avatar_url": identity.get("avatar_url") or (payload.get("profile") or {}).get("avatar_url"),
        })
    return out


def member_by_handle(group_id: str, handle: str) -> dict | None:
    target = (handle or "").strip().lstrip("@").lower()
    if not target:
        return None
    for member in members(group_id):
        if (member.get("handle") or "").lower() == target:
            return member
    return None


def recent_messages(group_id: str, limit: int = 50) -> list[dict]:
    bounded = max(1, min(int(limit or 50), 100))
    rows = (
        _sb().table("group_messages")
        .select("id,seq,sender_user_id,sender_kind,agent_for_user_id,reply_to_message_id,content,created_at")
        .eq("group_id", group_id)
        .order("seq", desc=True)
        .limit(bounded)
        .execute()
        .data
        or []
    )
    return list(reversed(rows))


def message(group_id: str, message_id: str) -> dict | None:
    rows = (
        _sb().table("group_messages")
        .select("id,seq,sender_user_id,sender_kind,agent_for_user_id,reply_to_message_id,content,created_at")
        .eq("group_id", group_id)
        .eq("id", message_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def messages_after(group_id: str, seq: int, limit: int = 100) -> list[dict]:
    rows = (
        _sb().table("group_messages")
        .select("id,seq,sender_user_id,sender_kind,agent_for_user_id,content,created_at")
        .eq("group_id", group_id)
        .gt("seq", max(0, int(seq or 0)))
        .order("seq")
        .limit(max(1, min(int(limit or 100), 200)))
        .execute()
        .data
        or []
    )
    return rows


def send_agent_message(
    group_id: str,
    agent_for_user_id: str,
    content: str,
    reply_to_message_id: str | None,
    client_id: str,
) -> dict:
    return _rpc_result("network_send_agent_group_message", {
        "p_group": group_id,
        "p_agent_for": agent_for_user_id,
        "p_content": content,
        "p_reply_to": reply_to_message_id,
        "p_client_id": client_id,
    })


def enqueue_agent_replies(message_id: str, user_ids: list[str]) -> dict:
    return _rpc_result("network_enqueue_group_agent_replies", {
        "p_message": message_id,
        "p_users": user_ids or [],
    })


def get_agent_preference(user_id: str) -> dict:
    rows = (
        _sb().table("group_agent_preferences")
        .select("enabled,updated_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {"enabled": True, "updated_at": None}


def set_agent_preference(user_id: str, enabled: bool) -> dict:
    rows = (
        _sb().table("group_agent_preferences")
        .upsert({"user_id": user_id, "enabled": bool(enabled)}, on_conflict="user_id")
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {"enabled": bool(enabled)}


def claim_job() -> dict | None:
    return _rpc_result("network_claim_group_agent_job", {})


def finish_job(job_id: str, ok: bool, error: str | None = None) -> dict:
    return _rpc_result("network_finish_group_agent_job", {
        "p_job": job_id, "p_ok": ok, "p_error": error,
    })


def summary(group_id: str) -> dict | None:
    rows = (
        _sb().table("group_memory")
        .select("id,content,metadata,updated_at")
        .eq("group_id", group_id)
        .eq("kind", "summary")
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def facts(group_id: str, limit: int = 30) -> list[dict]:
    rows = (
        _sb().table("group_memory")
        .select("id,content,metadata,source_message_id,created_at")
        .eq("group_id", group_id)
        .eq("kind", "fact")
        .order("created_at", desc=True)
        .limit(max(1, min(int(limit or 30), 100)))
        .execute()
        .data
        or []
    )
    return rows


def list_memory(user_id: str, group_id: str, limit: int = 30) -> dict:
    _require_member(group_id, user_id)
    return _rpc_result("network_group_memory_list", {
        "p_user": user_id, "p_group": group_id, "p_limit": limit,
    })


def search_memory(user_id: str, group_id: str, query: str, limit: int = 8) -> dict:
    _require_member(group_id, user_id)
    q = (query or "").strip()
    if not q:
        return {"group_id": group_id, "query": "", "results": []}
    vector = _embed(q)
    if not vector:
        return {"group_id": group_id, "query": q, "results": [], "error": "Semantic search is unavailable"}
    results = _rpc_result("network_group_memory_search", {
        "p_user": user_id, "p_group": group_id,
        "p_query_embedding": vector, "p_limit": max(1, min(int(limit or 8), 20)),
    })
    return {"group_id": group_id, "query": q, "results": results or []}


def _message_content(group_id: str, message_id: str) -> str:
    rows = (
        _sb().table("group_messages")
        .select("content")
        .eq("id", message_id)
        .eq("group_id", group_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "Message not found")
    return (rows[0].get("content") or "").strip()


def remember_message(user_id: str, group_id: str, message_id: str) -> dict:
    _require_member(group_id, user_id)
    content = _message_content(group_id, message_id)
    if not content:
        raise HTTPException(422, "That message has nothing to remember")
    return _rpc_result("network_group_memory_remember", {
        "p_user": user_id, "p_group": group_id, "p_message": message_id,
        "p_content_hash": content_hash(content),
        "p_embedding": _embed(content),
    })


def add_fact(user_id: str, group_id: str, content: str) -> dict:
    _require_member(group_id, user_id)
    text = (content or "").strip()
    if not text:
        raise HTTPException(422, "Write something to remember")
    return _rpc_result("network_group_memory_add_fact", {
        "p_user": user_id, "p_group": group_id, "p_content": text[:4000],
        "p_content_hash": content_hash(text[:4000]),
        "p_embedding": _embed(text[:4000]),
    })


def pending_summaries(min_messages: int, limit: int = 5) -> list[dict]:
    result = _rpc_result("network_groups_needing_summary", {
        "p_min_messages": max(1, int(min_messages)),
        "p_limit": max(1, min(int(limit), 20)),
    })
    return result or []


def embed_pending(limit: int = 12) -> int:
    """Fill embeddings for summaries/facts written by the worker or a retry."""
    rows = (
        _sb().table("group_memory")
        .select("id,content")
        .is_("embedding", "null")
        .order("created_at")
        .limit(max(1, min(int(limit or 12), 50)))
        .execute()
        .data
        or []
    )
    updated = 0
    for row in rows:
        vector = _embed(row.get("content") or "")
        if not vector:
            continue
        _sb().table("group_memory").update({"embedding": vector}).eq("id", row["id"]).execute()
        updated += 1
    return updated


def set_summary(group_id: str, content: str, through_seq: int, metadata: dict | None = None) -> dict:
    text = (content or "").strip()
    if not text:
        raise HTTPException(422, "Summary cannot be empty")
    return _rpc_result("network_group_memory_set_summary", {
        "p_group": group_id,
        "p_content": text[:4000],
        "p_content_hash": content_hash(text[:4000]),
        "p_through_seq": max(0, int(through_seq)),
        "p_embedding": _embed(text[:4000]),
        "p_metadata": metadata or {},
    })


def add_system_fact(group_id: str, content: str, metadata: dict | None = None) -> dict:
    """A fact distilled from a summary; no human author."""
    text = (content or "").strip()
    if not text:
        raise HTTPException(422, "Fact cannot be empty")
    digest = content_hash(text[:4000])
    existing = (
        _sb().table("group_memory")
        .select("id,content,metadata,created_at")
        .eq("group_id", group_id)
        .eq("content_hash", digest)
        .eq("kind", "fact")
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return existing[0]
    inserted = _sb().table("group_memory").insert({
        "group_id": group_id,
        "kind": "fact",
        "content": text[:4000],
        "content_hash": digest,
        "metadata": metadata or {"source": "summary"},
        "embedding": _embed(text[:4000]),
    }).execute().data or []
    return inserted[0] if inserted else {}
