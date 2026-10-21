"""Clean up facts stored before the unified write path (Phase 5 of ZYND_MEMORY_QUALITY_PLAN.md).

Dry run by default: prints a per-user summary and writes dedupe_report.json, changes nothing.

    uv run python scripts/dedupe_memory.py                       # dry run, every user
    uv run python scripts/dedupe_memory.py --user <uuid>         # dry run, one user
    uv run python scripts/dedupe_memory.py --apply --confirm-database zynd
    uv run python scripts/dedupe_memory.py --undo <run_id> --confirm-database zynd

Order for production (needs a human's go-ahead, AGENTS.md section 6): run on a restored copy, review
dedupe_report.json with a person, apply with their approval, then recompute match embeddings:

    uv run python -m app.jobs recompute

Facts are archived (valid_until), never deleted; every change is an assertion_history row tagged with
the run id, and --undo restores the exact previous active set. Facts the owner approved onto their
card are never touched. --apply and --undo refuse to run unless --confirm-database names the
database in DATABASE_URL, so a wrong environment variable cannot reach production by accident.
"""
import argparse
import asyncio
import json
import pathlib
import sys
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import close_pool, get_pool, init_pool  # noqa: E402
from app.services import cleanup  # noqa: E402


def _target() -> tuple[str, str]:
    parts = urlsplit(settings.database_url)
    return parts.hostname or "?", (parts.path or "/").lstrip("/") or "?"


async def main(args: argparse.Namespace) -> int:
    host, dbname = _target()
    mutating = bool(args.apply or args.undo)
    if mutating and args.confirm_database != dbname:
        print(f"refusing: DATABASE_URL points at database {dbname!r} on {host}; "
              f"pass --confirm-database {dbname} to proceed")
        return 2
    await init_pool()
    pool = get_pool()
    try:
        if args.undo:
            result = await cleanup.undo(pool, args.undo)
            print(f"undo {args.undo}: {result}")
            return 0

        run_id = cleanup.new_run_id()
        users = [args.user] if args.user else await cleanup.user_ids(pool)
        report = {"run_id": run_id, "mode": "apply" if args.apply else "dry-run",
                  "database": {"host": host, "name": dbname}, "users": [], "totals": {}}
        totals: dict[str, int] = {}
        for user_id in users:
            async with pool.acquire() as conn:
                plan = cleanup.plan_user(user_id, await cleanup.load_facts(conn, user_id))
            if not plan.actions:
                continue
            entry = {"user_id": user_id, "counts": plan.counts, "actions": [a.as_dict() for a in plan.actions]}
            if args.apply:
                entry["applied"] = await cleanup.apply_plan(pool, plan, run_id)
            report["users"].append(entry)
            for key, n in plan.counts.items():
                totals[key] = totals.get(key, 0) + n
            print(f"{user_id}: {plan.counts}")
        report["totals"] = totals
        pathlib.Path(args.report).write_text(json.dumps(report, indent=1, default=str) + "\n")
        verb = "applied" if args.apply else "would change"
        print(f"\nrun {run_id}: {verb} {sum(totals.values())} facts for {len(report['users'])} of {len(users)} users "
              f"{totals}; report: {args.report}")
        if args.apply:
            print(f"undo with: --undo {run_id} --confirm-database {dbname}\nthen: uv run python -m app.jobs recompute")
        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", help="only this user id")
    parser.add_argument("--apply", action="store_true", help="perform the plan (default is a dry run)")
    parser.add_argument("--undo", metavar="RUN_ID", help="reverse a previous --apply run")
    parser.add_argument("--confirm-database", default="", help="name of the database in DATABASE_URL; required to apply or undo")
    parser.add_argument("--report", default="dedupe_report.json")
    sys.exit(asyncio.run(main(parser.parse_args())))
