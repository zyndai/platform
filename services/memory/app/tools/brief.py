import logging

from supabase import create_client, Client

from app.config import settings

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def _sb() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def _persona_row(user_id: str) -> dict | None:
    result = (
        _sb().table("persona_agents")
        .select("description,brief_content")
        .eq("user_id", user_id)
        .eq("active", True)
        .execute()
    )
    return result.data[0] if result.data else None


def _current_brief(user_id: str) -> str:
    row = _persona_row(user_id)
    return (row.get("brief_content") or "").strip() if row else ""


async def read_my_brief(user_id: str) -> dict:
    try:
        row = _persona_row(user_id)
    except Exception as e:
        logger.exception(f"[brief] read_my_brief failed: {e}")
        return {"success": False, "error": str(e)}

    if row is None:
        return {
            "success": True,
            "exists": False,
            "content": "",
            "fallback_description": "",
        }
    return {
        "success": True,
        "exists": True,
        "content": (row.get("brief_content") or "").strip(),
        "fallback_description": row.get("description") or "",
    }


async def append_to_my_brief(user_id: str, text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        return {"success": False, "error": "Nothing to append — `text` was empty."}

    try:
        existing = _current_brief(user_id)
        body = text if text.endswith("\n") else text + "\n"
        new_content = (existing.rstrip() + "\n\n" + body.rstrip() + "\n") if existing else body
        _sb().table("persona_agents").update(
            {"brief_content": new_content}
        ).eq("user_id", user_id).execute()
    except Exception as e:
        logger.exception(f"[brief] append_to_my_brief failed: {e}")
        return {"success": False, "error": str(e)}

    return {"success": True, "appended": text.strip()}


async def replace_my_brief(user_id: str, content: str) -> dict:
    if content is None:
        content = ""

    try:
        _sb().table("persona_agents").update(
            {"brief_content": content or None}
        ).eq("user_id", user_id).execute()
    except Exception as e:
        logger.exception(f"[brief] replace_my_brief failed: {e}")
        return {"success": False, "error": str(e)}

    return {"success": True, "content": content}


async def clear_my_brief(user_id: str) -> dict:
    return await replace_my_brief(user_id, "")


async def add_todo(user_id: str, title: str) -> dict:
    if not isinstance(title, str) or not title.strip():
        return {"success": False, "error": "Nothing to add — `title` was empty."}

    cleaned = title.strip()
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip()

    try:
        sb = _sb()
        row = sb.table("brief_todos").insert({
            "user_id": user_id, "title": cleaned, "source_text": cleaned, "done": False,
        }).execute()
        inserted_id = row.data[0]["id"] if row.data else None
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "todo_id": inserted_id, "title": cleaned}
