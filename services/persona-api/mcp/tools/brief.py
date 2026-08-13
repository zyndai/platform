"""
Brief tools — MCP-registered functions for the principal's long-form Brief.

The Brief is a plain-text field stored on `persona_agents.brief_content`.
These tools wrap `agent.persona_manager` so the orchestrator can
read/append/replace/clear the Brief like any other tool — auto-injecting
`user_id` as the first arg.

`_ensure_brief_doc` verifies the user has a deployed persona (there is no
Google Doc to create anymore) and returns a structured error code
(`no_persona`) when the user can't act on the brief, so the Telegram
dispatcher (and the orchestrator) can surface a clickable next-step link
instead of a raw stack trace.

These tools are deliberately NOT added to any external allowlist —
the Brief is principal-private and must never be exposed to foreign
agents over A2A.
"""

from __future__ import annotations

import logging

from mcp.tools.error_utils import friendly_error, friendly_error_message

logger = logging.getLogger(__name__)


def _ensure_brief_doc(user_id: str) -> dict:
    """Return {"ok": True} if the user has a deployed persona, else a no_persona error."""
    from agent import persona_manager
    try:
        persona = persona_manager.get_persona_status(user_id)
        if persona.get("deployed"):
            return {"ok": True}
        return {
            "ok": False,
            "code": "no_persona",
            "message": "You haven't deployed a persona yet. Open the Zynd dashboard and finish onboarding.",
        }
    except Exception as e:
        logger.warning(f"[brief] ensure failed: {e}")
        return {"ok": False, "code": "no_persona", "message": "Couldn't confirm your persona is ready. Try again."}


def read_my_brief(user_id: str) -> dict:
    """Read the user's Brief — the long-form context this persona uses to
    know its principal. Returns the current plain-text body.

    Args:
        user_id: Injected automatically by the orchestrator.
    """
    from agent import persona_manager
    try:
        result = persona_manager.get_brief(user_id)
    except ValueError as e:
        return friendly_error("read your brief", e)
    except Exception as e:
        logger.exception(f"[brief] read_my_brief failed: {e}")
        return friendly_error("read your brief", e)

    return {
        "success": True,
        "exists": result.get("exists", True),
        "content": result.get("content") or "",
        "fallback_description": result.get("fallback_description") or "",
    }


def append_to_my_brief(user_id: str, text: str) -> dict:
    """Append a line (or lines) to the user's Brief. Use this when the user
    tells you something durable about themselves that you should remember
    across conversations.

    Args:
        user_id: Injected automatically by the orchestrator.
        text: The text to append. A trailing newline is added if missing.
    """
    if not isinstance(text, str) or not text.strip():
        return friendly_error_message(
            "add to your brief",
            "Nothing to append — `text` was empty.",
            hint="Tell me what you'd like me to add.",
        )

    ensured = _ensure_brief_doc(user_id)
    if not ensured.get("ok"):
        return {"success": False, "error": ensured["message"], "code": ensured["code"]}

    from agent import persona_manager
    try:
        current = persona_manager.get_brief(user_id)
    except ValueError as e:
        return friendly_error("add to your brief", e)

    existing = current.get("content") or ""
    body = text if text.endswith("\n") else text + "\n"
    new_content = (existing.rstrip() + "\n\n" + body.rstrip() + "\n") if existing else body
    result = persona_manager.save_brief_content(user_id, new_content)
    if not result.get("success"):
        return friendly_error_message("add to your brief", result.get("error") or "Append failed.")
    return {"success": True, "appended": text.strip()}


def replace_my_brief(user_id: str, content: str) -> dict:
    """Replace the entire body of the user's Brief with `content`.

    Args:
        user_id: Injected automatically by the orchestrator.
        content: The new full body of the brief. Pass an empty string
            to clear the brief (or use `clear_my_brief`).
    """
    if content is None:
        content = ""

    ensured = _ensure_brief_doc(user_id)
    if not ensured.get("ok"):
        return {"success": False, "error": ensured["message"], "code": ensured["code"]}

    from agent import persona_manager
    try:
        result = persona_manager.save_brief_content(user_id, content)
    except ValueError as e:
        return friendly_error("replace your brief", e)
    except Exception as e:
        logger.exception(f"[brief] replace_my_brief failed: {e}")
        return friendly_error("replace your brief", e)

    if not result.get("success"):
        return friendly_error_message("replace your brief", result.get("error") or "Replace failed.")
    return {"success": True, "content": content}


def clear_my_brief(user_id: str) -> dict:
    """Empty the user's Brief. Only its stored text is wiped.

    Args:
        user_id: Injected automatically by the orchestrator.
    """
    return replace_my_brief(user_id, "")


def add_todo(user_id: str, title: str) -> dict:
    """Add an actionable todo to the user's todo list.

    Direct write into the `brief_todos` table — bypasses the
    brief_watcher's 5-minute poll cycle so the new item shows up on
    the dashboard's Todos tab immediately. Use this whenever the user
    explicitly asks to remember something as a todo / task / action item
    ('add a todo', 'remind me to', 'put X on my list'). Do NOT use it
    to record general profile facts — those belong in the Brief via
    `append_to_my_brief`.

    Args:
        user_id: Injected automatically by the orchestrator.
        title: Short imperative phrase, ~3–12 words. The function
            trims whitespace and caps overly-long input.
    """
    if not isinstance(title, str) or not title.strip():
        return friendly_error_message(
            "add a todo",
            "Nothing to add — `title` was empty.",
            hint="Tell me the task you want to add, e.g. 'Email Sarah about the demo'.",
        )

    cleaned = title.strip()
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip()

    import config

    try:
        sb = config.get_supabase()
        row = sb.table("brief_todos").insert({
            "user_id": user_id,
            "title": cleaned,
            "source_text": cleaned,
            "done": False,
        }).execute()
        inserted_id = row.data[0]["id"] if row.data else None
    except Exception as e:
        logger.warning(f"[brief] add_todo failed: {e}")
        return friendly_error("add the todo", e)

    return {
        "success": True,
        "todo_id": inserted_id,
        "title": cleaned,
    }
