"""Search quality gate: precision@k and recall@5 over the golden queries."""
from tests import search_golden


def test_golden_queries_meet_the_targets():
    results = search_golden.evaluate()
    summary = search_golden.summarize(results)
    targets = search_golden.load()["targets"]
    misses = [f"{r.target!r}: want {r.relevant} got {r.top}" for r in results if r.precision < 1 or r.recall < 1]
    assert summary["precision_at_k"] >= targets["precision_at_k"], (summary, misses)
    assert summary["recall_at_5"] >= targets["recall_at_5"], (summary, misses)


def test_no_non_investor_outranks_an_investor_on_an_investor_query():
    """Phase 1 gate: on queries that ask for an investor, whoever is not one (the corpus names its
    investors inv_*) only ever follows every investor in the results."""
    results = search_golden.evaluate()
    roles = {q["target"]: q["role"] for q in search_golden.load()["queries"]}
    for r in results:
        if roles[r.target] != "investor":
            continue
        kinds = [h.startswith("inv_") for h in r.top]
        assert kinds == sorted(kinds, reverse=True), (r.target, r.top)


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


def test_memorys_real_parameters_surface_the_right_people():
    """The parameters memory's find_people sends (services/memory/tests/fixtures/people_golden.json),
    run through the scorer as the API would: topics soft, skills only when explicit, filters relaxed."""
    import json
    import pathlib
    from unittest.mock import MagicMock, patch

    from services import search as search_service

    path = pathlib.Path(__file__).resolve().parents[2] / "memory" / "tests" / "fixtures" / "people_golden.json"
    if not path.exists():
        import pytest
        pytest.skip("memory's fixture is not in this checkout")
    doc = search_golden.load()
    rows = search_golden.build_rows(doc)
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc: score the whole corpus")
    misses = []
    with patch.object(search_service.config, "get_supabase", lambda: sb), \
         patch.object(search_service, "embed_text", search_golden.hash_embed), \
         patch.object(search_service, "SEM_FLOOR", search_golden.HASH_SEM_FLOOR), \
         patch.object(search_service, "SEM_SPAN", search_golden.HASH_SEM_SPAN), \
         patch.object(search_service.cards_service, "list_published_rows", lambda **kw: rows):
        for case in json.loads(path.read_text())["cases"]:
            p = case["params"]
            found = search_service.search_agents(
                q=p["q"], role=p.get("role", ""), location=p.get("location", ""), skills=p.get("skills", ""),
                topics=p.get("topics", ""), relax=p.get("relax") == "true", limit=5, include_unclaimed=True)
            top = [r["handle"] for r in found]
            k = min(5, len(case["relevant"]))
            if not set(top[:k]) <= set(case["relevant"]) or not set(case["relevant"]) <= set(top):
                misses.append(f"{case['target']!r}: want {case['relevant']} got {top}")
    assert not misses, misses
