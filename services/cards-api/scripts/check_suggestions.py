"""Read-only: the people search plan's Phase 2 "done when" checks, on live data.

    cd services/cards-api && python scripts/check_suggestions.py [--limit 200] [--days 14]

Needs the usual SUPABASE_* and OPENAI settings (suggestions embed their target text). It never
writes: suggestions are computed live (the stored table is not read), and the digest days are
simulated in memory. For each claimed card it checks:

  1. exclusions   no suggestion has a connection row with the owner (any status), is hidden by
                  them, or is unclaimed. Checked against the tables directly, not through the
                  code under test.
  2. rotation     over --days simulated daily digests (2 people a day, the real cooldown), the
                  share of each day's people the owner was not shown in the previous 7 days.
                  Target: at least 60%.
  3. two-way      of the cards for which some claimed card is a kind the owner wants and wants
                  to meet someone like the owner, how many get at least one two-way suggestion.
                  Target: all of them.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from services import cards as cards_service  # noqa: E402
from services import match_prefs, suggestions, two_way  # noqa: E402

DIGEST_PEOPLE = 2
ROTATION_WINDOW_DAYS = 7


def connected_card_ids(user_id: str) -> set[str]:
    rows = (config.get_supabase().table("connections").select("requester_user_id,requester_card_id,recipient_card_id")
            .or_(f"requester_user_id.eq.{user_id},recipient_user_id.eq.{user_id}").execute().data or [])
    return {r["recipient_card_id"] if r["requester_user_id"] == user_id else r["requester_card_id"] for r in rows}


def simulate_digests(row: dict, people: list[dict], days: int) -> list[float]:
    """Each day's share of new people (not shown in the previous ROTATION_WINDOW_DAYS)."""
    shown_on: dict[str, int] = {}          # card id -> last day shown
    best_score: dict[str, float] = {}
    shares = []
    for day in range(days):
        recent = {cid: best_score[cid] for cid, d in shown_on.items() if day - d < suggestions.COOLDOWN_DAYS}
        pool = [p for p in people if p["card_id"] not in recent or p["score"] > recent[p["card_id"]] + suggestions.RESHOW_GAIN]
        today = suggestions.diversify(pool, DIGEST_PEOPLE)
        if not today:
            continue
        new = [p for p in today if day - shown_on.get(p["card_id"], -10**6) >= ROTATION_WINDOW_DAYS]
        shares.append(len(new) / len(today))
        for p in today:
            shown_on[p["card_id"]] = day
            best_score[p["card_id"]] = max(best_score.get(p["card_id"], 0.0), p["score"])
    return shares


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="check only the first N claimed cards")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    rows = [r for r in cards_service.list_published_rows(columns="id,handle,owner_user_id,owner_email,card")
            if (r.get("owner_email") or "").strip() and r.get("owner_user_id")]
    claimed_ids = {r["id"] for r in rows}
    cards = {r["id"]: suggestions._card(r) for r in rows}
    if args.limit:
        rows = rows[: args.limit]

    violations, empty, shares = [], 0, []
    two_way_possible = two_way_found = 0
    cache: dict = {}
    for row in rows:
        people = suggestions.compute(row, embed_cache=cache)
        if not people:
            empty += 1
        connected = connected_card_ids(row["owner_user_id"])
        hidden = set(match_prefs.get(row["owner_user_id"])["hide_person"])
        for p in people:
            if p["card_id"] in connected:
                violations.append(f"{row['handle']}: {p['handle']} has a connection row")
            if p["handle"] in hidden:
                violations.append(f"{row['handle']}: {p['handle']} is hidden")
            if p["card_id"] not in claimed_ids:
                violations.append(f"{row['handle']}: {p['handle']} is unclaimed")
        shares += simulate_digests(row, people, args.days)
        me = cards[row["id"]]
        mine = two_way.kinds_of(me) if me else set()
        wanted = two_way.wanted_kinds(me) if me else set()
        # Both ways: the owner wants their kind, and they want the owner's.
        candidates = [cid for cid, c in cards.items()
                      if c and cid != row["id"] and cid not in connected
                      and two_way.two_way_match(mine, c) and two_way.kinds_of(c) & wanted]
        if candidates:
            two_way_possible += 1
            two_way_found += any(p["two_way"] for p in people)
        print(f"{row['handle']:<32} {len(people):3} people  "
              f"{sum(p['two_way'] for p in people):2} two-way  first: {people[0]['handle'] if people else '-'}")

    print()
    print(f"cards checked:        {len(rows)}  (no suggestions: {empty})")
    print(f"exclusion violations: {len(violations)}  (target 0)")
    for v in violations[:20]:
        print("   ", v)
    rotation = statistics.mean(shares) if shares else 0.0
    print(f"digest rotation:      {rotation:.0%} of each day's people new vs the previous "
          f"{ROTATION_WINDOW_DAYS} days  (target >= 60%)")
    print(f"two-way:              {two_way_found}/{two_way_possible} cards that could get one did  (target all)")


if __name__ == "__main__":
    main()
