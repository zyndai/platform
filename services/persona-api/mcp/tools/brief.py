"""
Brief tools — MCP-registered functions for the principal's long-form
Brief Google Doc.

The Brief is a Google Doc owned by the user but created (and writable)
by the persona agent under `drive.file` scope. Its doc_id is stored on
`persona_agents.brief_doc_id`. These tools wrap `agent.persona_manager`
so the orchestrator can read/append/replace/clear the Brief like any
other tool — auto-injecting `user_id` as the first arg.

Auto-init: replace/append/clear all lazily create the Brief if it
doesn't exist yet, so the LLM never has to call a separate "init"
tool. `_ensure_brief_doc` returns a structured error code (`no_persona`
/ `google_unavailable`) when init fails for a reason the user can
actually act on, so the Telegram dispatcher (and the orchestrator) can
surface a clickable next-step link instead of a raw stack trace.

These tools are deliberately NOT added to any external allowlist —
the Brief is principal-private and must never be exposed to foreign
agents over A2A.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _ensure_brief_doc(user_id: str) -> dict:
    """Make sure the user has a Brief Google Doc; create it if not.

    Return shapes:
      {"ok": True}                       — doc already existed
      {"ok": True, "created": True}      — doc was just created
      {"ok": False, "code": "no_persona", "message": ...}
      {"ok": False, "code": "google_unavailable", "message": ...}
    """
    from agent import persona_manager

    try:
        existing = persona_manager.get_brief(user_id)
        if existing.get("exists"):
            return {"ok": True}
    except ValueError as e:
        # get_brief raises ValueError("No active persona") when there's no
        # deployed persona — treat the same as init's no_persona case.
        if "No active persona" in str(e):
            return {
                "ok": False,
                "code": "no_persona",
                "message": (
                    "You haven't deployed a persona yet. Open the Zynd "
                    "dashboard and finish onboarding."
                ),
            }
        # Any other ValueError from get_brief — fall through to init,
        # which will raise the proper signal.
    except Exception as e:
        logger.warning(f"[brief] get_brief probe failed, will try init: {e}")

    try:
        persona_manager.init_brief_doc(user_id)
        return {"ok": True, "created": True}
    except ValueError as e:
        msg = str(e)
        if "No active persona" in msg:
            return {
                "ok": False,
                "code": "no_persona",
                "message": (
                    "You haven't deployed a persona yet. Open the Zynd "
                    "dashboard and finish onboarding."
                ),
            }
        # Other ValueErrors from init_brief_doc bubble up from the Docs
        # create call — treat as google_unavailable so the user gets a
        # link to the OAuth re-connect flow.
        logger.warning(f"[brief] init_brief_doc failed: {e}")
        return {
            "ok": False,
            "code": "google_unavailable",
            "message": (
                "I need Google Drive access to create your brief. "
                "Connect Google in Settings → Accounts: "
                "https://persona.zynd.ink/dashboard/settings/accounts"
            ),
        }
    except Exception as e:
        logger.warning(f"[brief] init_brief_doc unexpected failure: {e}")
        return {
            "ok": False,
            "code": "google_unavailable",
            "message": (
                "I need Google Drive access to create your brief. "
                "Connect Google in Settings → Accounts: "
                "https://persona.zynd.ink/dashboard/settings/accounts"
            ),
        }


def read_my_brief(user_id: str) -> dict:
    """Read the user's Brief — the long-form context doc this persona
    uses to know its principal. Returns the current plain-text body,
    the Google Doc URL, and whether the brief exists yet.

    Args:
        user_id: Injected automatically by the orchestrator.
    """
    from agent import persona_manager

    try:
        result = persona_manager.get_brief(user_id)
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
            "message": (
                "You don't have a brief yet. Ask me to add something and "
                "I'll create one — e.g. 'add to my brief: I prefer "
                "afternoon meetings.'"
            ),
        }

    if result.get("error"):
        return {
            "success": False,
            "error": result["error"],
            "doc_id": result.get("doc_id"),
            "url": result.get("url"),
        }

    return {
        "success": True,
        "exists": True,
        "content": result.get("content") or "",
        "url": result.get("url") or "",
        "doc_id": result.get("doc_id"),
    }


def append_to_my_brief(user_id: str, text: str) -> dict:
    """Append a line (or lines) to the user's Brief Google Doc. Creates
    the brief lazily if it doesn't exist yet. Use this when the user
    tells you something durable about themselves that you should
    remember across conversations.

    Args:
        user_id: Injected automatically by the orchestrator.
        text: The text to append. A trailing newline is added if missing.
    """
    if not isinstance(text, str) or not text.strip():
        return {"success": False, "error": "Nothing to append — `text` was empty."}

    ensured = _ensure_brief_doc(user_id)
    if not ensured.get("ok"):
        return {
            "success": False,
            "error": ensured["message"],
            "code": ensured["code"],
        }

    from agent import persona_manager
    from mcp.tools.google.docs import append_to_document

    status = persona_manager.get_persona_status(user_id)
    doc_id = status.get("brief_doc_id")
    if not doc_id:
        return {
            "success": False,
            "error": "Brief doc id missing after init — try again.",
            "code": "google_unavailable",
        }

    body = text if text.endswith("\n") else text + "\n"
    result = append_to_document(user_id=user_id, document_id=doc_id, text=body)
    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "Append failed."}

    return {
        "success": True,
        "doc_id": doc_id,
        "url": status.get("brief_doc_url") or "",
        "appended": text.strip(),
    }


def replace_my_brief(user_id: str, content: str) -> dict:
    """Replace the entire body of the user's Brief Google Doc with
    `content`. Creates the brief lazily if it doesn't exist yet.

    Args:
        user_id: Injected automatically by the orchestrator.
        content: The new full body of the brief. Pass an empty string
            to clear the brief (or use `clear_my_brief`).
    """
    if content is None:
        content = ""

    ensured = _ensure_brief_doc(user_id)
    if not ensured.get("ok"):
        return {
            "success": False,
            "error": ensured["message"],
            "code": ensured["code"],
        }

    from agent import persona_manager

    try:
        result = persona_manager.save_brief_content(user_id, content)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[brief] replace_my_brief failed: {e}")
        return {"success": False, "error": str(e)}

    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "Replace failed."}

    status = persona_manager.get_persona_status(user_id)
    return {
        "success": True,
        "doc_id": result.get("doc_id"),
        "url": status.get("brief_doc_url") or "",
        "content": content,
    }


def clear_my_brief(user_id: str) -> dict:
    """Empty the user's Brief Google Doc. The doc itself stays — only
    its body is wiped.

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
        return {"success": False, "error": "Nothing to add — `title` was empty."}

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
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "todo_id": inserted_id,
        "title": cleaned,
    }
