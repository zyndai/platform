"""Shared self-context lookup used by HTTP and MCP surfaces."""
from __future__ import annotations

import asyncio
import json
import logging

from app.services import persona
from app.tools import brief as brief_tools

logger = logging.getLogger("zynd.self_context")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_socials(persona_status: dict | None, stored: object) -> dict[str, str]:
    """Merge persona links over memory-stored links, using the public aliases."""
    profile = (persona_status or {}).get("profile") or {}
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            stored = {}
    stored_links = stored if isinstance(stored, dict) else {}
    result: dict[str, str] = {}
    for key in ("linkedin", "github", "x", "instagram", "website"):
        persona_key = "twitter" if key == "x" else key
        value = _text(profile.get(persona_key)) or _text(profile.get(key)) or _text(stored_links.get(key))
        if key == "x":
            value = value or _text(stored_links.get("twitter"))
        result[key] = value
    return result


async def read_brief(uid: str) -> str | None:
    """Keep the synchronous Supabase read off the caller's event loop."""
    try:
        result = await asyncio.to_thread(lambda: asyncio.run(brief_tools.read_my_brief(uid)))
        return _text(result.get("content")) or None if result.get("success") else None
    except Exception:
        logger.info("brief unavailable for %s", uid, exc_info=True)
        return None


def normalize_profile(persona_status: dict | None) -> dict:
    status = persona_status or {}
    profile = status.get("profile") or {}
    return {
        "name": _text(status.get("name")),
        "title": _text(profile.get("title")),
        "organization": _text(profile.get("organization")),
        "location": _text(profile.get("location")),
        "capabilities": status.get("capabilities") or [],
        "interests": profile.get("interests") or [],
        "description": _text(status.get("description")),
        "socials": normalize_socials(persona_status, {}),
    }


async def load_self_context(pool, uid: str) -> dict:
    """Load local identity and at most one best-effort persona status.

    The conditional UPDATE makes the display-name self-heal safe against a
    concurrent explicit name change.
    """
    row = await pool.fetchrow(
        "SELECT display_name, email, supabase_user_id, socials FROM users WHERE id = $1",
        uid,
    )
    if not row:
        raise LookupError("user not found")

    display_name = _text(row["display_name"])
    email = _text(row["email"])
    supabase_user_id = _text(row["supabase_user_id"]) or None
    persona_status = None
    if supabase_user_id:
        try:
            persona_status = await persona.get_status(supabase_user_id)
        except Exception:
            logger.info("persona status unavailable for %s", uid, exc_info=True)

    persona_name = _text((persona_status or {}).get("name"))
    local_part = email.split("@", 1)[0].strip() if "@" in email else ""
    resolved_name = display_name or persona_name or local_part or "ZYND user"
    if not display_name and persona_name:
        try:
            await pool.execute(
                """UPDATE users SET display_name = $1 WHERE id = $2
                   AND (display_name IS NULL OR btrim(display_name) = '')""",
                persona_name,
                uid,
            )
        except Exception:
            logger.info("failed to self-heal display name for %s", uid, exc_info=True)

    return {
        "identity": {"name": resolved_name, "email": email or None},
        "persona_status": persona_status,
        "supabase_user_id": supabase_user_id,
        "socials": normalize_socials(persona_status, row["socials"]),
    }
