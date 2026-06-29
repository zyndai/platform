"""Bridge ZYND users to the persona network: connect, message, meet, social links.

Resolves the caller (and any target) through the users table — supabase_user_id keys
persona, persona_agent_id is the network identity. Every op is gated by persona_enabled;
when off, raises SocialDisabled so tools can degrade with a clear message.
"""
import asyncpg

from app.config import settings
from app.services import persona


class SocialDisabled(RuntimeError):
    pass


def _require_enabled() -> None:
    if not settings.persona_enabled:
        raise SocialDisabled("persona features are not enabled yet")


async def _ids(pool: asyncpg.Pool, zynd_user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT supabase_user_id, persona_agent_id, display_name FROM users WHERE id = $1",
        zynd_user_id)


async def set_social(pool: asyncpg.Pool, user_id: str, links: dict) -> None:
    _require_enabled()
    me = await _ids(pool, user_id)
    if not (me and me["supabase_user_id"]):
        raise ValueError("you have no linked persona identity yet")
    await persona.update_social(me["supabase_user_id"], links)


async def connect(pool: asyncpg.Pool, user_id: str, target_user_id: str, message: str) -> dict:
    _require_enabled()
    me = await _ids(pool, user_id)
    tgt = await _ids(pool, target_user_id)
    if not (me and me["supabase_user_id"]):
        raise ValueError("you have no persona — connect after your persona is set up")
    if not (tgt and tgt["persona_agent_id"]):
        raise ValueError("that person has no persona to connect to")
    return await persona.introduce(
        me["supabase_user_id"], tgt["persona_agent_id"], tgt["display_name"] or "ZYND user", message)


async def send_message(pool: asyncpg.Pool, user_id: str, thread_id: str, content: str) -> dict:
    _require_enabled()
    me = await _ids(pool, user_id)
    if not (me and me["supabase_user_id"]):
        raise ValueError("you have no persona")
    return await persona.send_message(me["supabase_user_id"], thread_id, content)


async def connections(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    _require_enabled()
    me = await _ids(pool, user_id)
    if not (me and me["persona_agent_id"]):
        return []
    return await persona.list_connections(me["persona_agent_id"])


async def book_meeting(pool: asyncpg.Pool, user_id: str, thread_id: str, payload: dict) -> dict:
    _require_enabled()
    me = await _ids(pool, user_id)
    if not (me and me["supabase_user_id"]):
        raise ValueError("you have no persona")
    return await persona.create_meeting(me["supabase_user_id"], thread_id, payload)
