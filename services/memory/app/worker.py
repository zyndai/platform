"""Async worker (arq). Runs the heavy half of the ingestion pipeline so the
/ingest endpoint can return in <200ms (brief §5, stages 3-6).

Pipeline per chunk:  embed -> extract -> resolve entities -> upsert assertions.
M5 will add an embedding_recompute enqueue at the end.
"""
import logging

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.db import close_pool, get_pool, init_pool, to_pgvector
from app.services.assertions import upsert_assertion
from app.services.decay import run_decay_job, run_orphan_cleanup
from app.services.embeddings import embed
from app.services.entities import resolve_entity
from app.services.extraction import extract_assertions
from app.services.matching import recompute_user_embeddings, run_recompute_all

logger = logging.getLogger("zynd.worker")


async def chunk_processor(ctx: dict, chunk_id: str) -> dict:
    pool = get_pool()

    chunk = await pool.fetchrow(
        """SELECT user_id, raw_text, source_system, observed_at, embedding
             FROM trace_chunks WHERE id = $1""",
        chunk_id,
    )
    if chunk is None:
        logger.warning("chunk %s vanished before processing", chunk_id)
        return {"chunk_id": chunk_id, "status": "missing"}

    user_id = str(chunk["user_id"])
    source_system = chunk["source_system"]

    # Stage 3 — embed. Only if not already embedded (idempotent on retry).
    if chunk["embedding"] is None:
        vector = to_pgvector(await embed(chunk["raw_text"]))
        await pool.execute(
            "UPDATE trace_chunks SET embedding = $1::vector WHERE id = $2",
            vector, chunk_id,
        )

    # Stage 4 — extract (already validated against the taxonomy).
    extracted = await extract_assertions(chunk["raw_text"])
    if not extracted:
        return {"chunk_id": chunk_id, "status": "ok", "assertions": 0}

    # Stages 5-6 — resolve + upsert, one transaction per assertion so a single
    # bad row can't roll back the whole chunk.
    written = 0
    async with pool.acquire() as conn:
        for item in extracted:
            async with conn.transaction():
                entity_id = await resolve_entity(conn, user_id, item.object_name, item.object_type)
                await upsert_assertion(
                    conn,
                    user_id=user_id,
                    extracted=item,
                    object_entity_id=entity_id,
                    source_system=source_system,
                    trace_chunk_id=chunk_id,
                    observed_at=chunk["observed_at"],
                )
            written += 1

    # Stage: refresh this user's matching vectors now that their graph changed.
    # ctx["redis"] is present under arq; absent when chunk_processor is called
    # directly (e.g. tests), in which case recompute is triggered separately.
    redis = ctx.get("redis")
    if written and redis is not None:
        await redis.enqueue_job("recompute_user", user_id)

    logger.info("chunk %s -> %d assertions", chunk_id, written)
    return {"chunk_id": chunk_id, "status": "ok", "assertions": written}


async def recompute_user(ctx: dict, user_id: str) -> dict:
    result = await recompute_user_embeddings(get_pool(), user_id)
    logger.info("recompute %s -> %s", user_id, result)
    return {"user_id": user_id, "clusters": result}


async def decay_cron(ctx: dict) -> dict:
    result = await run_decay_job(get_pool())
    logger.info("decay_job: %s", result)
    return result


async def orphan_cron(ctx: dict) -> dict:
    result = await run_orphan_cleanup(get_pool())
    logger.info("orphan_cleanup: %s", result)
    return result


async def recompute_all_cron(ctx: dict) -> dict:
    result = await run_recompute_all(get_pool())
    logger.info("recompute_all: %s", result)
    return result


async def resolution_cron(ctx: dict) -> dict:
    from app.services.resolution import run_resolution_detector
    result = await run_resolution_detector(get_pool())
    logger.info("resolution_detector: %s", result)
    return result


async def on_startup(ctx: dict) -> None:
    await init_pool()


async def on_shutdown(ctx: dict) -> None:
    await close_pool()


async def cleanup_pages_cron(ctx: dict) -> dict:
    pool = get_pool()
    from app.services.pages import cleanup_expired_pages as cleanup_pg
    from app.services.pages_agent import cleanup_expired_pages as cleanup_sb
    pg_count = await cleanup_pg(pool)
    sb_count = cleanup_sb()
    logger.info("cleanup_pages: postgres=%d supabase=%d", pg_count, sb_count)
    return {"postgres": pg_count, "supabase": sb_count}


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [chunk_processor, recompute_user, cleanup_pages_cron]
    # Brief §9: decay nightly 00:30 UTC; recompute + orphan cleanup nightly/weekly.
    # cleanup_pages: hourly expire of anonymous/ttl pages.
    cron_jobs = [
        cron(decay_cron, hour=0, minute=30),
        cron(resolution_cron, hour=1, minute=30),   # v2: emit is_resolved after decay settles
        cron(recompute_all_cron, hour=2, minute=0),
        cron(orphan_cron, weekday="sun", hour=1, minute=0),
        cron(cleanup_pages_cron, minute=0),  # hourly: delete expired anonymous pages
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = 3
