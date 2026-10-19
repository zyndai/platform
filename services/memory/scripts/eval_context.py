"""Score ranked context against the hand-labelled eval set, optionally sweeping RELATED_MIN.

Use this with REAL embeddings to pick RELATED_MIN (CI runs the same labels with mock
embeddings, which only know word overlap):

    createdb zynd_eval && psql zynd_eval -c 'CREATE EXTENSION vector'
    DATABASE_URL=postgresql://localhost/zynd_eval OPENAI_API_KEY=... MOCK_LLM=false \\
      uv run python scripts/eval_context.py --sweep 0.35 0.40 0.45 0.50 0.55

It seeds synthetic users into the target database, so it refuses any database whose
name does not contain "eval" or "test".
"""
import argparse
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from app.config import settings  # noqa: E402
from app.db import close_pool, get_pool, init_pool  # noqa: E402
from app.services import export  # noqa: E402
from app.taxonomy import RELATED_MIN  # noqa: E402

import context_eval  # noqa: E402


async def main(sweep: list[float], verbose: bool) -> int:
    dbname = settings.database_url.rsplit("/", 1)[-1].split("?")[0]
    if "eval" not in dbname and "test" not in dbname:
        print(f"refusing to seed synthetic users into database {dbname!r}")
        return 2
    await init_pool()
    pool = get_pool()
    try:
        await pool.execute((ROOT / "sql" / "schema.sql").read_text())
        print(f"embeddings: {'mock' if settings.mock_llm else settings.embedding_model}")
        for value in sweep or [RELATED_MIN]:
            export.RELATED_MIN = value
            await pool.execute(
                "TRUNCATE assertion_history, assertions, user_embeddings, entities, trace_chunks "
                "RESTART IDENTITY CASCADE")
            report = await context_eval.run(pool)
            print(f"RELATED_MIN={value:.2f}  {report.summary()}")
            if verbose:
                for line in report.failures():
                    print("   ", line)
        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep", type=float, nargs="*", default=[], help="RELATED_MIN values to try")
    parser.add_argument("-v", "--verbose", action="store_true", help="list failing queries")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.sweep, args.verbose)))
