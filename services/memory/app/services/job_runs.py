"""When did each nightly job last run? Backs the decay line in /health.

Decay silently not running looks exactly like "facts never fade", so the worker records every
run and /health reports how long ago the last one was.
"""
from __future__ import annotations

import json
import logging

import asyncpg

logger = logging.getLogger(__name__)

DECAY_MAX_AGE_HOURS = 48


async def record(pool: asyncpg.Pool, job: str, summary: dict) -> None:
    """Remember that `job` just ran. Never raises: a missing table (schema not applied yet)
    must not fail the job it is describing."""
    try:
        await pool.execute(
            """INSERT INTO job_runs (job, last_run_at, summary) VALUES ($1, now(), $2::jsonb)
               ON CONFLICT (job) DO UPDATE SET last_run_at = now(), summary = EXCLUDED.summary""",
            job, json.dumps(summary, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not record run of %s: %s", job, exc)


async def status(pool: asyncpg.Pool, job: str, max_age_hours: float) -> dict:
    """{last_run_at, age_hours, ok}; ok is False when the job never ran or ran too long ago."""
    try:
        row = await pool.fetchrow(
            """SELECT last_run_at, EXTRACT(EPOCH FROM (now() - last_run_at)) / 3600.0 AS age_hours, summary
                 FROM job_runs WHERE job = $1""", job)
    except Exception as exc:  # noqa: BLE001
        return {"last_run_at": None, "age_hours": None, "ok": False, "error": type(exc).__name__}
    if row is None:
        return {"last_run_at": None, "age_hours": None, "ok": False}
    age = round(float(row["age_hours"]), 1)
    return {"last_run_at": row["last_run_at"].isoformat(), "age_hours": age, "ok": age <= max_age_hours}
