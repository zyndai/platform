"""Read-only: time card search and print the cosine range the score is calibrated on.

    cd services/cards-api && python scripts/bench_search.py [--runs 20]

Needs the usual SUPABASE_* and OPENAI settings (it embeds each query). It only reads. Use it
(1) before and after applying packages/db cards 0030 to compare p95 (target: under 800 ms for a
filtered search on prod-size data), and (2) to re-fit SEM_FLOOR / SEM_SPAN in services/search.py:
the printed cosines of the top and the 50th-ranked cards show where related text ends and
unrelated text begins for the real embedding model.
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import search  # noqa: E402

QUERIES = [
    dict(q="seed-stage investor who backs AI dev tools in India", role="investor", location="India"),
    dict(q="founders building AI agents", role="founder"),
    dict(q="machine learning engineer Bangalore", role="engineer", location="Bangalore"),
    dict(q="rust developer", skills="rust"),
    dict(q="designer in Berlin", role="designer", location="Berlin"),
    dict(q="developer tools"),
]


def p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20)[-1] if len(values) >= 2 else values[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    runs = ap.parse_args().runs
    times: list[float] = []
    for query in QUERIES:
        took = []
        for _ in range(runs):
            start = time.perf_counter()
            found = search.search_agents(limit=50, include_unclaimed=True, relax=True, **query)
            took.append((time.perf_counter() - start) * 1000)
        times += took
        scores = [r["match_score"] for r in found]
        print(f"{query['q'][:50]:50} p50 {statistics.median(took):6.0f} ms  p95 {p95(took):6.0f} ms  "
              f"results {len(found):2}  top {scores[0] if scores else 0:.2f}  50th {scores[-1] if scores else 0:.2f}")
    print(f"\nall queries: p50 {statistics.median(times):.0f} ms  p95 {p95(times):.0f} ms")


if __name__ == "__main__":
    main()
