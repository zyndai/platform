"""Seed a user's ZYND memory from their persona profile.

When a user authenticates and we resolve their persona (ZYND and persona share one
Supabase project), pull what they already told persona — bio, role, org, location,
skills, interests — and ingest it as ZYND memory so their context graph isn't empty
on day one. No manual feeding.

Idempotent by construction: the assembled text is deterministic, so an unchanged
profile collides on the trace_chunk content hash and is skipped; a changed profile
re-seeds the delta. Best-effort and never raises — login must not depend on persona.
"""
import logging
from datetime import datetime, timezone

import asyncpg

from app.config import settings
from app.models import Turn
from app.services import persona
from app.services.ingest import ingest_turns

logger = logging.getLogger("zynd.persona")

# trace_chunks.source_system tag for profile-derived memory (distinguishes it from
# chat-derived chunks and lets us audit/forget the seeded set as a unit).
_SOURCE = "persona_seeded"
# Below this the profile carries no extractable signal — don't bother ingesting.
_MIN_SEED_CHARS = 12


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_list(value: object) -> list[str]:
    """Persona stores capabilities as a list and interests as either a list or a
    comma string; normalise both to a clean, order-preserving list."""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _profile_text(status: dict) -> str:
    """Assemble first-person sentences from a persona status dict so the extractor
    reads them as the user's own facts. Deterministic ordering → stable content hash."""
    profile = status.get("profile") or {}
    parts: list[str] = []

    description = _clean(status.get("description"))
    if description:
        parts.append(description if description.endswith((".", "!", "?")) else description + ".")

    title = _clean(profile.get("title"))
    organization = _clean(profile.get("organization"))
    if title and organization:
        parts.append(f"I work as {title} at {organization}.")
    elif title:
        parts.append(f"My role is {title}.")
    elif organization:
        parts.append(f"I work at {organization}.")

    location = _clean(profile.get("location"))
    if location:
        parts.append(f"I am based in {location}.")

    capabilities = _as_list(status.get("capabilities"))
    if capabilities:
        parts.append(f"I have expertise in {', '.join(capabilities)}.")

    interests = _as_list(profile.get("interests"))
    if interests:
        parts.append(f"I am interested in {', '.join(interests)}.")

    return " ".join(parts)


async def seed_persona_profile(pool: asyncpg.Pool, arq, user_id: str, supabase_sub: str) -> dict:
    """Fetch the user's persona profile and ingest it as ZYND memory.

    Call after a successful persona link (agent_id resolved). Best-effort: any
    failure is logged and swallowed so it can never block authentication.
    """
    if not (settings.persona_enabled and supabase_sub):
        return {"seeded": False, "reason": "persona disabled"}
    try:
        status = await persona.get_status(supabase_sub)
        if not (status and status.get("deployed") and status.get("agent_id")):
            return {"seeded": False, "reason": "no persona profile"}
        text = _profile_text(status)
        if len(text) < _MIN_SEED_CHARS:
            return {"seeded": False, "reason": "profile too sparse"}
        turn = Turn(role="user", content=text, timestamp=datetime.now(timezone.utc))
        inserted, _ = await ingest_turns(pool, arq, user_id, _SOURCE, [turn], min_chars=1)
        return {"seeded": inserted > 0, "chars": len(text)}
    except Exception as exc:  # invariant: seeding must never break login
        logger.warning("persona seed failed for user %s: %s", user_id, exc)
        return {"seeded": False, "reason": "error"}
