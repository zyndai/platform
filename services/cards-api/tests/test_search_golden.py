"""Search quality gate: precision@k and recall@5 over the golden queries."""
from tests import search_golden


def test_golden_queries_meet_the_targets():
    results = search_golden.evaluate()
    summary = search_golden.summarize(results)
    targets = search_golden.load()["targets"]
    misses = [f"{r.target!r}: want {r.relevant} got {r.top}" for r in results if r.precision < 1 or r.recall < 1]
    assert summary["precision_at_k"] >= targets["precision_at_k"], (summary, misses)
    assert summary["recall_at_5"] >= targets["recall_at_5"], (summary, misses)


def test_fixture_labels_point_at_real_cards():
    doc = search_golden.load()
    handles = {c["handle"] for c in doc["cards"]}
    assert len(doc["queries"]) >= 50 - 1 and len(handles) == len(doc["cards"])
    for query in doc["queries"]:
        assert set(query["relevant"]) <= handles, query["target"]


def test_stopword_only_query_returns_nothing():
    from unittest.mock import patch
    from services import search as search_service
    with patch.object(search_service, "embed_text", lambda q: pytest_fail()):
        assert search_service.search_agents(q="who is in the", include_unclaimed=True) == []


def pytest_fail():
    raise AssertionError("embedding a stopword-only query would match noise")
