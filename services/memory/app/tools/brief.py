
import logging

from app.services import persona_brief

logger = logging.getLogger(__name__)


async def read_my_brief(user_id: str) -> dict:
    try:
        result = await persona_brief.get_brief(user_id)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[brief] read_my_brief failed: {e}")
        return {"success": False, "error": str(e)}

    if not result.get("exists"):
        return {
            "success": True,
            "exists": False,
            "content": "",
            "fallback_description": result.get("fallback_description") or "",
            "message": "You don't have a brief yet. Ask me to add something and I'll create one.",
        }
    if result.get("error"):
        return {"success": False, "error": result["error"], "doc_id": result.get("doc_id"), "url": result.get("url")}

    return {
        "success": True,
        "exists": True,
        "content": result.get("content") or "",
        "url": result.get("url") or "",
        "doc_id": result.get("doc_id"),
    }


async def append_to_my_brief(user_id: str, text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        return {"success": False, "error": "Nothing to append — `text` was empty."}

    try:
        ensured = await persona_brief.init_brief_doc(user_id)
    except ValueError as e:
        msg = str(e)
        if "No active persona" in msg:
            return {"success": False, "error": msg, "code": "no_persona"}
        if "Google" in msg or "Failed to create brief doc" in msg:
            return {"success": False, "error": msg, "code": "google_unavailable"}
        return {"success": False, "error": msg, "code": "google_unavailable"}

    status = persona_brief.get_persona_status(user_id)
    doc_id = status.get("brief_doc_id")
    if not doc_id:
        return {"success": False, "error": "Brief doc id missing after init — try again.", "code": "google_unavailable"}

    body = text if text.endswith("\n") else text + "\n"
    from app.tools.google.docs import append_to_google_doc
    result = await append_to_google_doc(user_id=user_id, document_id=doc_id, text=body)
    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "Append failed."}

    return {"success": True, "doc_id": doc_id, "url": status.get("brief_doc_url") or "", "appended": text.strip()}


async def replace_my_brief(user_id: str, content: str) -> dict:
    if content is None:
        content = ""

    try:
        ensured = await persona_brief.init_brief_doc(user_id)
    except ValueError as e:
        msg = str(e)
        if "No active persona" in msg:
            return {"success": False, "error": msg, "code": "no_persona"}
        return {"success": False, "error": msg, "code": "google_unavailable"}

    try:
        result = await persona_brief.save_brief_content(user_id, content)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[brief] replace_my_brief failed: {e}")
        return {"success": False, "error": str(e)}

    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "Replace failed."}

    status = persona_brief.get_persona_status(user_id)
    return {"success": True, "doc_id": result.get("doc_id"), "url": status.get("brief_doc_url") or "", "content": content}


async def clear_my_brief(user_id: str) -> dict:
    return await replace_my_brief(user_id, "")


async def add_todo(user_id: str, title: str) -> dict:
    if not isinstance(title, str) or not title.strip():
        return {"success": False, "error": "Nothing to add — `title` was empty."}

    cleaned = title.strip()
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip()

    import logging
    from supabase import create_client
    from app.config import settings

    try:
        sb = create_client(settings.supabase_url, settings.supabase_service_key)
        row = sb.table("brief_todos").insert({
            "user_id": user_id, "title": cleaned, "source_text": cleaned, "done": False,
        }).execute()
        inserted_id = row.data[0]["id"] if row.data else None
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "todo_id": inserted_id, "title": cleaned}
