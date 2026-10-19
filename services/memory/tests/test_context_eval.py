"""Ranked-context quality gate. Needs Postgres + pgvector (-m integration)."""
import pytest

import context_eval
from app.config import settings


@pytest.mark.integration
async def test_ranked_context_meets_the_eval_targets(pg, monkeypatch):
    monkeypatch.setattr(settings, "feature_ranked_context", True)
    report = await context_eval.run(pg)
    print(report.summary())
    targets = report.targets
    assert report.recall >= targets["recall"], report.failures()
    assert report.precision >= targets["precision"], report.failures()


def test_fixture_is_well_formed():
    doc = context_eval.load()
    assert len(doc["users"]) >= 10
    for user in doc["users"]:
        names = {fact[1] for fact in user["facts"]}
        topics = [q["topic"] for q in user["queries"]]
        assert None in topics and sum(t is not None for t in topics) >= 3, user["id"]
        for query in user["queries"]:
            # a label that names a fact the user doesn't have can never be satisfied
            assert set(query["expect"]) <= names, (user["id"], query["expect"])
            assert set(query["forbid"]) <= names, (user["id"], query["forbid"])
            assert not set(query["expect"]) & set(query["forbid"])
