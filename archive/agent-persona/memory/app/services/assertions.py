import asyncpg

from app.models import ExtractedAssertion
from app.taxonomy import (
    DEFAULT_SOURCE_RELIABILITY,
    FINDABILITY_PREDICATES,
    SOURCE_RELIABILITY,
    decay_fn_for,
)

CONFIDENCE_CAP = 0.97  # brief §14.4 — never reach certainty


def bayesian_update(prior: float, evidence: float, source_reliability: float) -> float:
    """Brief §5.4. New evidence pushes confidence toward 1.0 but never past 0.97.

    For a brand-new assertion we pass prior=0.0, so the first stored confidence
    is evidence * source_reliability (a chatgpt-sourced 0.9 lands at 0.72).
    """
    likelihood = evidence * source_reliability
    updated = prior + likelihood * (1 - prior)
    return min(round(updated, 4), CONFIDENCE_CAP)


async def upsert_assertion(
    conn: asyncpg.Connection,
    user_id: str,
    extracted: ExtractedAssertion,
    object_entity_id: str,
    source_system: str,
    trace_chunk_id: str,
    observed_at,
) -> str:
    """Insert a new assertion or Bayesian-update an existing one, logging every
    change to assertion_history. Must run inside a transaction (caller owns it).

    Identity of an assertion at MVP = (user_id, predicate, object_entity_id);
    subject is always the user themselves (§3.4).
    """
    reliability = SOURCE_RELIABILITY.get(source_system, DEFAULT_SOURCE_RELIABILITY)

    existing = await conn.fetchrow(
        """SELECT id, confidence FROM assertions
           WHERE user_id = $1 AND predicate = $2 AND object_entity_id = $3
             AND valid_until IS NULL""",
        user_id, extracted.predicate, object_entity_id,
    )

    if existing is None:
        confidence = bayesian_update(0.0, extracted.confidence, reliability)
        # Findability-eligible facts are public by default so the matching pool is
        # always populated (matching reads only is_public=true). Every other predicate
        # — beliefs, frustrations, health/life-stage, etc. — stays PRIVATE. Users can
        # still revoke a public fact via /me/revoke.
        is_public = extracted.predicate in FINDABILITY_PREDICATES
        row = await conn.fetchrow(
            """INSERT INTO assertions
                 (user_id, predicate, object_entity_id, confidence,
                  source_system, trace_chunk_id, decay_fn, observed_at,
                  is_public, approved_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                       CASE WHEN $9 THEN now() ELSE NULL END)
               RETURNING id""",
            user_id, extracted.predicate, object_entity_id, confidence,
            source_system, trace_chunk_id, decay_fn_for(extracted.predicate), observed_at,
            is_public,
        )
        assertion_id = str(row["id"])
        await _log_history(conn, assertion_id, None, confidence, "new_evidence")
        return assertion_id

    assertion_id = str(existing["id"])
    prior = float(existing["confidence"])
    confidence = bayesian_update(prior, extracted.confidence, reliability)
    await conn.execute(
        """UPDATE assertions
              SET confidence = $1, version = version + 1,
                  source_system = $2, trace_chunk_id = $3, observed_at = $4
            WHERE id = $5""",
        confidence, source_system, trace_chunk_id, observed_at, assertion_id,
    )
    await _log_history(conn, assertion_id, prior, confidence, "new_evidence")
    return assertion_id


async def _log_history(
    conn: asyncpg.Connection,
    assertion_id: str,
    prev_confidence: float | None,
    new_confidence: float,
    change_reason: str,
) -> None:
    await conn.execute(
        """INSERT INTO assertion_history
             (assertion_id, prev_confidence, new_confidence, change_reason)
           VALUES ($1, $2, $3, $4)""",
        assertion_id, prev_confidence, new_confidence, change_reason,
    )
