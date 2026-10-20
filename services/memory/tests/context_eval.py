"""Eval harness for ranked context (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md, Phase 1 step 6).

Seeds each synthetic user from fixtures/context_eval.json, runs `rank_context` for every
labelled query and scores it:

  recall    = expected names that came back / expected names
  precision = expected names that came back / (those + forbidden names that came back)

Names that are neither expected nor forbidden are ignored, so the labels stay small.
Shared by tests/test_context_eval.py (mock embeddings, CI) and scripts/eval_context.py
(real embeddings, tuning RELATED_MIN by hand).
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from seed import make_user, seed_fact

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "context_eval.json"


@dataclass
class QueryResult:
    user: str
    topic: str | None
    returned: list[str]
    missed: list[str]
    leaked: list[str]
    hits: int
    expected: int


@dataclass
class Report:
    results: list[QueryResult] = field(default_factory=list)
    targets: dict = field(default_factory=dict)

    @property
    def recall(self) -> float:
        expected = sum(r.expected for r in self.results)
        return sum(r.hits for r in self.results) / expected if expected else 1.0

    @property
    def precision(self) -> float:
        hits = sum(r.hits for r in self.results)
        leaks = sum(len(r.leaked) for r in self.results)
        return hits / (hits + leaks) if hits + leaks else 1.0

    def failures(self) -> list[str]:
        return [
            f"{r.user} topic={r.topic!r}: missed={r.missed} leaked={r.leaked} returned={r.returned}"
            for r in self.results if r.missed or r.leaked
        ]

    def summary(self) -> str:
        return (f"queries={len(self.results)} recall={self.recall:.3f} "
                f"precision={self.precision:.3f} failing={len(self.failures())}")


def load() -> dict:
    return json.loads(FIXTURE.read_text())


async def run(pool, doc: dict | None = None) -> Report:
    from app.services.export import rank_context

    doc = doc or load()
    report = Report(targets=doc.get("targets", {}))
    for user in doc["users"]:
        uid = await make_user(pool)   # unique email: users survive the per-test TRUNCATE
        for predicate, name, etype, confidence, days in user["facts"]:
            await seed_fact(pool, uid, predicate, name, etype, confidence=confidence, days_ago=days)
        for query in user["queries"]:
            facts = await rank_context(pool, uid, topic=query["topic"], k=user["k"])
            returned = [f["object"] for f in facts]
            expect, forbid = query["expect"], query["forbid"]
            report.results.append(QueryResult(
                user=user["id"], topic=query["topic"], returned=returned,
                missed=[n for n in expect if n not in returned],
                leaked=[n for n in forbid if n in returned],
                hits=len([n for n in expect if n in returned]), expected=len(expect),
            ))
    return report
