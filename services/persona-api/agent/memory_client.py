"""
Memory Layer Client — typed HTTP client for the ZYND assertion graph.

Integrates agent-persona with the memory-layer backend so personas can:
  1. Retrieve relevant user context before building the system prompt.
  2. Ingest conversation turns after each exchange for long-term memory.
  3. Confirm / forget facts on behalf of the user.

All calls are fire-and-forget safe — memory-layer being down never
blocks the persona from responding.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

# ── Data types ───────────────────────────────────────────────────────


@dataclass
class MemoryAssertion:
    """A single fact the memory layer knows about a user."""

    statement: str          # human-readable assertion
    predicate: str          # e.g. is_working_on, is_interested_in
    object: str             # the object value
    object_type: str        # entity type
    confidence: float       # 0.0–0.97
    relevance: float = 1.0  # cosine similarity to the query topic (if topic-scoped)


@dataclass
class MemoryContext:
    """A page of relevant assertions loaded for a prompt."""

    assertions: list[MemoryAssertion] = field(default_factory=list)
    from_cache: bool = False
    error: str | None = None


@dataclass
class IngestResult:
    chunks_inserted: int = 0
    chunks_skipped: int = 0
    error: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def is_enabled() -> bool:
    """Memory features are enabled when a shared JWT secret is configured.

    Public so every caller (orchestrator, nudge_engine, digital_twin,
    daily_brief, proactive_loop, twin.py, ...) checks the same thing one
    way instead of re-testing ``config.MEMORY_LAYER_JWT_SECRET`` truthiness
    inline everywhere.
    """
    return bool(config.MEMORY_LAYER_JWT_SECRET)


def _make_jwt(user_id: str) -> str:
    """Create a short-lived ZYND JWT for the given user.

    Uses the shared HS256 secret so memory-layer can verify the token.
    """
    try:
        import jwt  # pyjwt — already in requirements via python-jose
    except ImportError:
        import jose.jwt as jwt  # fallback to python-jose

    now = int(time.time())
    payload = {
        "sub": user_id,
        "iss": "zynd",
        "typ": "access",
        "iat": now,
        "exp": now + 300,  # 5 minutes — enough for a single request
    }
    return jwt.encode(payload, config.MEMORY_LAYER_JWT_SECRET, algorithm="HS256")


def _client() -> httpx.AsyncClient:
    """Return a shared httpx client with the memory-layer base URL."""
    return httpx.AsyncClient(
        base_url=config.MEMORY_LAYER_URL.rstrip("/"),
        timeout=httpx.Timeout(10.0, connect=5.0),
    )


# ── Public API ───────────────────────────────────────────────────────


async def get_context(
    user_id: str,
    topic: str,
    k: int | None = None,
    min_confidence: float | None = None,
) -> MemoryContext:
    """Fetch topic-relevant assertions from the user's memory graph.

    Args:
        user_id: The Supabase user UUID (same in both agent-persona and memory-layer).
        topic: Natural-language query for semantic search over assertions.
        k: Max assertions to return (default from config).
        min_confidence: Minimum confidence threshold (default from config).

    Returns:
        MemoryContext with assertions sorted by relevance (highest first).
        On error, returns empty context with error set — callers should
        degrade gracefully.
    """
    if not is_enabled():
        return MemoryContext()

    if k is None:
        k = config.MEMORY_LAYER_MAX_CONTEXT_ASSERTIONS
    if min_confidence is None:
        min_confidence = config.MEMORY_LAYER_MIN_CONFIDENCE

    token = _make_jwt(user_id)

    try:
        async with _client() as client:
            resp = await client.post(
                f"/context/{user_id}",
                json={"topic": topic, "k": k},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 403:
                logger.debug(
                    "[memory] /context 403 for %s — user has no memory-layer account yet",
                    user_id,
                )
                return MemoryContext()
            resp.raise_for_status()

            raw: list[dict[str, Any]] = resp.json()
            assertions = [
                MemoryAssertion(
                    statement=item.get("statement", ""),
                    predicate=item.get("predicate", "unknown"),
                    object=item.get("object", ""),
                    object_type=item.get("object_type", "unknown"),
                    confidence=float(item.get("confidence", 0.0)),
                    relevance=float(item.get("relevance", 0.0)),
                )
                for item in raw
                if float(item.get("confidence", 0)) >= min_confidence
            ]
            # Sort by relevance descending so the most important facts come first.
            assertions.sort(key=lambda a: a.relevance, reverse=True)

            logger.debug(
                "[memory] loaded %d assertions for %s (topic=%r, confidence≥%.1f)",
                len(assertions), user_id, topic[:60], min_confidence,
            )
            return MemoryContext(assertions=assertions)

    except httpx.TimeoutException:
        logger.warning("[memory] /context timed out for %s", user_id)
        return MemoryContext(error="timeout")
    except httpx.HTTPStatusError as exc:
        logger.warning("[memory] /context HTTP %s for %s", exc.response.status_code, user_id)
        return MemoryContext(error=f"http_{exc.response.status_code}")
    except Exception as exc:
        logger.warning("[memory] /context failed for %s: %s", user_id, exc)
        return MemoryContext(error=str(exc)[:120])


async def list_assertions(user_id: str) -> list[MemoryAssertion]:
    """Fetch the user's full active assertion graph — every current fact,
    unranked (no topic filter, no confidence cutoff).

    Distinct from `get_context`: that's a topic-scoped, ranked slice for
    prompt injection; this is "everything", for surfaces like a settings
    page where the user wants to see (and confirm/forget) the whole graph.
    """
    if not is_enabled():
        return []

    token = _make_jwt(user_id)
    try:
        async with _client() as client:
            resp = await client.get(
                f"/users/{user_id}/graph",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            raw: list[dict[str, Any]] = resp.json()
            return [
                MemoryAssertion(
                    statement=item.get("statement", ""),
                    predicate=item.get("predicate", "unknown"),
                    object=item.get("object") or "",
                    object_type=item.get("object_type") or "unknown",
                    confidence=float(item.get("confidence", 0.0)),
                    relevance=1.0,
                )
                for item in raw
            ]
    except Exception as exc:
        logger.warning("[memory] /users/%s/graph failed: %s", user_id, exc)
        return []


async def ingest_turns(
    user_id: str,
    turns: list[dict[str, Any]],
    conversation_id: str | None = None,
    source_system: str = "agent-persona",
) -> IngestResult:
    """Persist conversation turns to the memory layer for async extraction.

    Only `role="user"` turns are processed by the memory pipeline (assistant
    turns are dropped server-side). This is fire-and-forget — errors are
    logged but never raised.

    Args:
        user_id: The Supabase user UUID.
        turns: List of dicts with `role` and `content` keys.
        conversation_id: Optional conversation identifier for grouping.
        source_system: Label for the originating system.
    """
    if not is_enabled():
        return IngestResult()
    if not turns:
        return IngestResult()

    token = _make_jwt(user_id)

    try:
        async with _client() as client:
            resp = await client.post(
                "/ingest",
                json={
                    "conversation_id": conversation_id,
                    "source_system": source_system,
                    "turns": turns,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            result = IngestResult(
                chunks_inserted=data.get("chunks_inserted", 0),
                chunks_skipped=data.get("chunks_skipped", 0),
            )
            logger.debug(
                "[memory] ingested %d turns for %s: %d inserted, %d skipped",
                len(turns), user_id, result.chunks_inserted, result.chunks_skipped,
            )
            return result

    except Exception as exc:
        logger.debug("[memory] /ingest failed for %s: %s", user_id, exc)
        return IngestResult(error=str(exc)[:120])


async def confirm_by_ref(user_id: str, predicate: str, obj: str) -> bool:
    """Confirm a fact by its exact (predicate, object) pair — the shape the
    memory-layer's FactRef actually requires (assertions have no stable id).
    Use this directly when the caller already has the exact pair (e.g. a
    settings UI listing real assertions); use `confirm_fact` when only a
    loose natural-language description is available."""
    if not is_enabled():
        return False

    token = _make_jwt(user_id)
    try:
        async with _client() as client:
            resp = await client.post(
                "/me/confirm",
                json={"predicate": predicate, "object": obj},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.debug("[memory] /confirm failed for %s: %s", user_id, exc)
        return False


async def forget_by_ref(user_id: str, predicate: str, obj: str) -> bool:
    """Forget a fact by its exact (predicate, object) pair. See `confirm_by_ref`."""
    if not is_enabled():
        return False

    token = _make_jwt(user_id)
    try:
        async with _client() as client:
            resp = await client.post(
                "/me/forget",
                json={"predicate": predicate, "object": obj},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.debug("[memory] /forget failed for %s: %s", user_id, exc)
        return False


async def _find_fact_ref(user_id: str, fact_statement: str) -> tuple[str, str] | None:
    """Resolve a loose natural-language fact description to the
    (predicate, object) pair the API needs, by matching it against the
    user's current graph. Returns None when nothing matches."""
    needle = (fact_statement or "").strip().lower()
    if not needle:
        return None
    assertions = await list_assertions(user_id)
    if not assertions:
        return None
    for a in assertions:
        if needle in a.statement.lower() or a.statement.lower() in needle:
            return (a.predicate, a.object)
    for a in assertions:
        if a.object and (needle in a.object.lower() or a.object.lower() in needle):
            return (a.predicate, a.object)
    return None


async def confirm_fact(user_id: str, fact_statement: str) -> bool:
    """Boost confidence on a fact the user has explicitly confirmed, given a
    loose natural-language description of it (see `_find_fact_ref`)."""
    ref = await _find_fact_ref(user_id, fact_statement)
    if not ref:
        logger.debug("[memory] /confirm: no assertion matched %r for %s", fact_statement, user_id)
        return False
    return await confirm_by_ref(user_id, *ref)


async def forget_fact(user_id: str, fact_statement: str) -> bool:
    """Decay a fact the user wants forgotten, given a loose natural-language
    description of it (see `_find_fact_ref`)."""
    ref = await _find_fact_ref(user_id, fact_statement)
    if not ref:
        logger.debug("[memory] /forget: no assertion matched %r for %s", fact_statement, user_id)
        return False
    return await forget_by_ref(user_id, *ref)
