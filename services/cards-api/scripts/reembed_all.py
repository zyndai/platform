"""Re-embed published cards so approved memory facts are searchable.

    python scripts/reembed_all.py                      # dry run
    python scripts/reembed_all.py --apply
    python scripts/reembed_all.py --apply --offset 0 --limit 100
    python scripts/reembed_all.py --apply --after-handle alice
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import cards as cards_service
from services import embed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offset", type=int, default=0, help="Skip the first N published rows")
    ap.add_argument("--limit", type=int, default=0, help="Process at most N rows (0 = all remaining)")
    ap.add_argument("--after-handle", default="", help="Resume after this handle (exclusive)")
    args = ap.parse_args()
    rows = cards_service.list_published_rows(columns="card,handle")
    rows = sorted(rows, key=lambda r: (r.get("handle") or ""))
    if args.after_handle:
        rows = [r for r in rows if (r.get("handle") or "") > args.after_handle]
    if args.offset:
        rows = rows[args.offset :]
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    print(f"published cards in batch: {len(rows)} (offset={args.offset} limit={args.limit or 'all'} after={args.after_handle or '-'})")
    if not args.apply:
        print("DRY RUN: pass --apply to write embeddings")
        for row in rows[:20]:
            print(f"  would re-embed {row.get('handle')}")
        if len(rows) > 20:
            print(f"  ... and {len(rows) - 20} more")
        return 0
    ok = fail = 0
    last_handle = ""
    for i, row in enumerate(rows, 1):
        handle = row.get("handle")
        if not handle:
            continue
        try:
            card = cards_service._row_to_card(row)
            vec = embed.embed_text(embed.card_search_text(card))
            if not vec:
                continue
            cards_service.config.get_supabase().table("agent_profile_cards").update(
                {"embedding": vec}
            ).eq("handle", handle).execute()
            ok += 1
            last_handle = handle
            if i % 25 == 0:
                print(f"progress re-embedded={ok} failed={fail} last={last_handle}")
        except Exception as exc:
            print(f"FAIL {handle}: {exc}", file=sys.stderr)
            fail += 1
    print(f"re-embedded={ok} failed={fail} last_handle={last_handle}")
    if last_handle:
        print(f"resume with: --after-handle {last_handle}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
