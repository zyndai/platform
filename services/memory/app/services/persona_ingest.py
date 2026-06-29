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


async def publish_persona_findability(pool: asyncpg.Pool, user_id: str, status: dict) -> int:
    """Auto-publish the safe findability fields from the persona profile as a PUBLIC,
    matchable card — persona is a discovery network, so being findable is the intent.

    Maps only free-text-safe predicates (is_seeking/open_to are enum-restricted, so we
    skip them). Each declare publishes + rebuilds the match vector. Idempotent: skips if
    the user already has a public card. Best-effort per field; never raises. Sensitive
    facts (health/politics/…) are never here — only FINDABILITY predicates are declared.
    Returns the number of fields published."""
    from app.services import findability
    try:
        if await findability.get_card(pool, user_id):
            return 0  # already published — don't re-declare on every login
    except Exception as exc:
        logger.warning("findability card check failed for %s: %s", user_id, exc)
        return 0

    profile = status.get("profile") or {}
    declarations: list[tuple[str, str]] = []
    declarations += [("has_expertise_in", c) for c in _as_list(status.get("capabilities"))]
    declarations += [("is_learning", i) for i in _as_list(profile.get("interests"))]
    organization = _clean(profile.get("organization"))
    if organization:
        declarations.append(("is_affiliated_with", organization))
    location = _clean(profile.get("location"))
    if location:
        declarations.append(("is_located_in", location))

    published = 0
    for predicate, value in declarations:
        try:
            await findability.declare(pool, user_id, predicate, value)
            published += 1
        except Exception as exc:  # bad value / embed hiccup — skip the field, keep going
            logger.warning("findability declare skipped (%s=%r) for %s: %s",
                           predicate, value, user_id, exc)
    return published


async def seed_persona_profile(pool: asyncpg.Pool, arq, user_id: str, supabase_sub: str) -> dict:
    """Fetch the user's persona profile, publish their findability card, and ingest the
    profile as ZYND memory.

    Call after a successful persona link (agent_id resolved). Best-effort: any failure is
    logged and swallowed so it can never block authentication.
    """
    if not (settings.persona_enabled and supabase_sub):
        return {"seeded": False, "reason": "persona disabled"}
    try:
        status = await persona.get_status(supabase_sub)
        if not (status and status.get("deployed") and status.get("agent_id")):
            return {"seeded": False, "reason": "no persona profile"}
        published = await publish_persona_findability(pool, user_id, status)
        text = _profile_text(status)
        inserted = 0
        if len(text) >= _MIN_SEED_CHARS:
            turn = Turn(role="user", content=text, timestamp=datetime.now(timezone.utc))
            inserted, _ = await ingest_turns(pool, arq, user_id, _SOURCE, [turn], min_chars=1)
        return {"seeded": inserted > 0, "published_findability": published, "chars": len(text)}
    except Exception as exc:  # invariant: seeding must never break login
        logger.warning("persona seed failed for user %s: %s", user_id, exc)
        return {"seeded": False, "reason": "error"}
