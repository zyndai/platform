"""
Profile tools — let the principal edit their own identity from chat.

The principal's name (`persona_agents.name`) is the authoritative identity
rendered into every system prompt as `principal_name`. Without a tool to
change it, the LLM has no way to update it and improvises by writing the new
name into the Brief — which then contradicts the name field and produces
"You're X (though your Brief says you go by Y)".

These tools are principal-private and never added to any external allowlist.
"""

from __future__ import annotations

import logging

from mcp.tools.error_utils import friendly_error

logger = logging.getLogger(__name__)


def update_my_name(user_id: str, name: str) -> dict:
    """Change the principal's name — the name this persona uses to identify
    the human it represents.

    Use this whenever the principal says their name is wrong, corrects you on
    their name, or asks to change it — e.g. "my name is actually X", "call me
    X", "change my name to X". Do NOT use `append_to_my_brief` for a name
    change: the name has its own field, and writing it into the Brief creates
    a contradiction the model then reports back as "you're A (though your
    Brief says B)".

    Args:
        user_id: Injected automatically by the orchestrator.
        name: The principal's real name, e.g. "Swapnil Shinde".
    """
    if not isinstance(name, str) or not name.strip():
        return {
            "success": False,
            "error": "Nothing to change — `name` was empty.",
            "error_message": "I need the new name to save.",
            "hint": "Tell me what name you'd like to use.",
        }

    cleaned = " ".join(name.strip().split())

    from agent import persona_manager

    try:
        persona_manager.update_persona_profile(user_id, {"name": cleaned})
    except ValueError as e:
        return friendly_error("update your name", e)
    except Exception as e:
        logger.exception("[profile] update_my_name failed: %s", e)
        return friendly_error("update your name", e)

    return {"success": True, "name": cleaned}
