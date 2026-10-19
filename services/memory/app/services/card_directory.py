"""Turn Zynd users into their Cards: the bridge between memory's people and the Cards index.

Memory knows people by user id; Cards, where a person is found and connected to, knows them
by handle. Search results are one list of Cards, so every Zynd user that matches is resolved
here. The name shown is the one on their Card (not the persona product), and a person
without a published, claimed Card is not a result: there is nobody to connect to.

Public identity only (handle, name, headline, location). Service-to-service over
MEMORY_SERVICE_TOKEN; a Cards outage degrades to "no Card found", never an exception.
"""
from __future__ import annotations

import logging
from uuid import UUID

import asyncpg
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_BATCH = 50


def enabled() -> bool:
    return bool(settings.cards_api_url and settings.memory_service_token)


def _as_uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


async def canonical_ids(pool: asyncpg.Pool, user_ids: list[str]) -> dict[str, str]:
    """memory user id -> the shared Zynd (Supabase) user id Cards knows them by.

    Rows from before the persona link carry users.id == the Supabase id and a NULL
    supabase_user_id, so the row's own id is the fallback.
    """
    ids = [u for u in dict.fromkeys(user_ids) if _as_uuid(u)]
    if not ids:
        return {}
    try:
        rows = await pool.fetch("SELECT id, supabase_user_id FROM users WHERE id = ANY($1::uuid[])", ids)
    except Exception as exc:  # noqa: BLE001 — best effort
        logger.warning("canonical id lookup failed: %s", exc)
        return {}
    out: dict[str, str] = {}
    for row in rows:
        canonical = _as_uuid(row["supabase_user_id"]) or _as_uuid(row["id"])
        if canonical:
            out[str(row["id"])] = canonical
    return out


async def cards_for_canonical(canonical: list[str]) -> dict[str, dict] | None:
    """Shared user id -> Card identity. None when Cards could not be asked (so callers can
    tell "no Card" from "could not check")."""
    ids = [c for c in dict.fromkeys(canonical) if c][:_MAX_BATCH]
    if not ids:
        return {}
    if not enabled():
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            resp = await client.post(
                settings.cards_api_url.rstrip("/") + "/internal/cards-for-users",
                json={"user_ids": ids},
                headers={"Authorization": "Bearer " + settings.memory_service_token},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cards-for-users failed: %s", exc)
        return None
    cards = payload.get("cards") if isinstance(payload, dict) else None
    return cards if isinstance(cards, dict) else None


async def cards_for_users(pool: asyncpg.Pool, user_ids: list[str]) -> dict[str, dict] | None:
    """memory user id -> Card identity for every id that has a published, claimed Card.
    None when Cards is unreachable or not configured."""
    canonical = await canonical_ids(pool, user_ids)
    cards = await cards_for_canonical(list(canonical.values()))
    if cards is None:
        return None
    return {uid: cards[c] for uid, c in canonical.items() if c in cards}
