
"""
Persona Brief — manages the Brief Google Doc for memory-layer.
Slim port of agent-persona/backend/agent/persona_manager.py (brief functions only).
"""
import logging

from supabase import create_client, Client

from app.config import settings
from app.tools.google.docs import (
    create_google_doc,
    append_to_google_doc,
    read_google_doc,
    replace_document_body,
)

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def _sb() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def get_persona_status(user_id: str) -> dict:
    sb = _sb()
    result = sb.table("persona_agents").select("*").eq("user_id", user_id).eq("active", True).execute()
    if not result.data:
        return {"deployed": False}
    persona = result.data[0]
    return {
        "deployed": True,
        "agent_id": persona["agent_id"],
        "name": persona["name"],
        "agent_handle": persona.get("agent_handle"),
        "description": persona["description"],
        "capabilities": persona["capabilities"],
        "profile": persona.get("profile", {}),
        "webhook_url": persona["webhook_url"],
        "public_key": persona["public_key"],
        "brief_doc_id": persona.get("brief_doc_id"),
        "brief_doc_url": persona.get("brief_doc_url"),
        "brief_doc_revision_id": persona.get("brief_doc_revision_id"),
    }


async def init_brief_doc(user_id: str) -> dict:
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise ValueError("No active persona — create a persona before initializing a brief.")

    if persona.get("brief_doc_id"):
        return {"doc_id": persona["brief_doc_id"], "url": persona.get("brief_doc_url") or "", "created": False}

    principal_name = persona.get("name") or "Your"
    title = f"Brief — {principal_name}"
    result = await create_google_doc(user_id=user_id, title=title)
    if not result.get("success"):
        raise ValueError(f"Failed to create brief doc: {result.get('error')}")

    doc_id = result["document_id"]
    doc_url = result["link"]

    seed = (persona.get("description") or "").strip()
    if seed:
        await append_to_google_doc(user_id=user_id, document_id=doc_id, text=seed + "\n")

    sb = _sb()
    sb.table("persona_agents").update({"brief_doc_id": doc_id, "brief_doc_url": doc_url}).eq("user_id", user_id).execute()

    logger.info(f"[brief] Initialized brief doc for {user_id}: {doc_id}")
    return {"doc_id": doc_id, "url": doc_url, "created": True}


async def get_brief(user_id: str) -> dict:
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise ValueError("No active persona.")

    doc_id = persona.get("brief_doc_id")
    if not doc_id:
        return {"exists": False, "fallback_description": persona.get("description") or ""}

    fetched = await read_google_doc(user_id=user_id, document_id=doc_id)
    if not fetched.get("success"):
        return {"exists": True, "doc_id": doc_id, "url": persona.get("brief_doc_url") or "", "content": "", "error": fetched.get("error")}

    return {"exists": True, "doc_id": doc_id, "url": persona.get("brief_doc_url") or "", "content": fetched.get("content") or "", "title": fetched.get("title")}


async def save_brief_content(user_id: str, content: str) -> dict:
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise ValueError("No active persona.")
    doc_id = persona.get("brief_doc_id")
    if not doc_id:
        raise ValueError("No brief doc to save into — initialize it first.")

    result = await replace_document_body(user_id=user_id, document_id=doc_id, text=content)
    if not result.get("success"):
        return {"success": False, "error": result.get("error")}

    try:
        sb = _sb()
        sb.table("persona_agents").update({"brief_content": content or None}).eq("user_id", user_id).execute()
    except Exception as e:
        logger.warning(f"[brief] brief_content DB sync failed (non-fatal): {e}")

    return {"success": True, "doc_id": doc_id, "content": content}
