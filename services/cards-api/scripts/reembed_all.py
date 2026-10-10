"""Re-embed published cards so approved memory facts are searchable.

    python scripts/reembed_all.py           # dry run
    python scripts/reembed_all.py --apply
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
    args = ap.parse_args()
    rows = cards_service.list_published_rows(columns="card,handle")
    print(f"published cards: {len(rows)}")
    if not args.apply:
        print("DRY RUN: pass --apply to write embeddings")
        return 0
    ok = fail = 0
    for row in rows:
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
        except Exception as exc:
            print(f"FAIL {handle}: {exc}", file=sys.stderr)
            fail += 1
    print(f"re-embedded={ok} failed={fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
