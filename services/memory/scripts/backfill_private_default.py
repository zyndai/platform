"""Unpublish facts that were auto-public on insert (S01 backfill).

Targets rows the old assertions.py path published itself:
  source = 'inferred'
  AND is_public
  AND approved_at IS NOT NULL
  AND approved_at is within 5 seconds of extracted_at
  (assertions has no created_at; extracted_at is the insert timestamp).

A real approve() sets approved_at later than insert, so those rows are kept.
Idempotent: a second run matches zero rows.

Run only after S02's empty-facts-clears-snapshot fix is live, then call
refresh_all_cards_memory so public cards drop the unpublished facts.

  uv run python scripts/backfill_private_default.py --dry-run
  uv run python scripts/backfill_private_default.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import close_pool, get_pool
from app.services.matching import recompute_user_embeddings

_SELECT = """
SELECT a.id, a.user_id, a.predicate, e.canonical_name AS object
  FROM assertions a
  JOIN entities e ON e.id = a.object_entity_id
 WHERE a.source = 'inferred'
   AND a.is_public = true
   AND a.approved_at IS NOT NULL
   AND a.valid_until IS NULL
   AND abs(extract(epoch FROM (a.approved_at - a.extracted_at))) < 5
 ORDER BY a.user_id, a.predicate
"""


async def run(dry_run: bool) -> int:
    pool = get_pool()
    rows = await pool.fetch(_SELECT)
    by_user: dict[str, list] = {}
    for row in rows:
        by_user.setdefault(str(row["user_id"]), []).append(row)

    print(f"{'DRY-RUN' if dry_run else 'APPLY'}: {len(rows)} auto-published inferred facts across {len(by_user)} users")
    for user_id, facts in by_user.items():
        sample = ", ".join(f"{f['predicate']}={f['object']}" for f in facts[:5])
        extra = f" (+{len(facts) - 5} more)" if len(facts) > 5 else ""
        print(f"  {user_id}: {len(facts)} — {sample}{extra}")

    if dry_run or not rows:
        await close_pool()
        return 0

    ids = [row["id"] for row in rows]
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE assertions
                  SET is_public = false, approved_at = NULL
                WHERE id = ANY($1::uuid[])""",
            ids,
        )
    for user_id in by_user:
        await recompute_user_embeddings(pool, user_id)
    print(f"unpublished {len(rows)} facts; recomputed embeddings for {len(by_user)} users")
    await close_pool()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report matches, change nothing")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.dry_run)))


if __name__ == "__main__":
    main()
