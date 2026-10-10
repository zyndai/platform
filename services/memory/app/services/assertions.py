import asyncpg

from app.config import settings
from app.models import ExtractedAssertion
from app.taxonomy import (
    DEFAULT_SOURCE_RELIABILITY,
    FINDABILITY_PREDICATES,
    SOURCE_RELIABILITY,
    decay_fn_for,
)

CONFIDENCE_CAP = 0.97  # brief §14.4 — never reach certainty


def initial_visibility(predicate: str) -> tuple[bool, None]:
    """Visibility for a brand-new inferred assertion.

    Private by default: is_public=false, approved_at=NULL. Publishing is a user
    action (findability.approve / declare), not a side effect of extraction.
    Flag off restores auto-public for findability predicates (rollback only).
    """
    is_public = (
        not settings.feature_s01_private_default
        and predicate in FINDABILITY_PREDICATES
    )
    return is_public, None


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

    New inferred facts are private (is_public=false, approved_at=NULL) until the
    owner approves them via findability.approve() or publishes via declare().
    Matching only reads is_public=true, so an unapproved fact never enters the pool.
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
        is_public, _approved_at = initial_visibility(extracted.predicate)
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
