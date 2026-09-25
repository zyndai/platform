"""Manual job runner for testing without waiting for cron.

    uv run python -m app.jobs decay     # run the decay job once
    uv run python -m app.jobs orphan    # run orphan cleanup once
"""
import asyncio
import sys

from app.db import close_pool, get_pool, init_pool
from app.services.decay import run_decay_job, run_orphan_cleanup
from app.services.matching import run_recompute_all

_JOBS = {"decay": run_decay_job, "orphan": run_orphan_cleanup, "recompute": run_recompute_all}


async def _main(job_name: str) -> None:
    job = _JOBS.get(job_name)
    if job is None:
        sys.exit(f"unknown job {job_name!r}; choose one of {sorted(_JOBS)}")
    await init_pool()
    try:
        result = await job(get_pool())
        print(f"{job_name}: {result}")
    finally:
        await close_pool()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.jobs <decay|orphan>")
    asyncio.run(_main(sys.argv[1]))
