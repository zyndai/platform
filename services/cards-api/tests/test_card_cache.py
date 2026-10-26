"""The in-process card snapshot (services/card_cache.py): the same results as the database path,
one database read for a whole relaxed search, and nothing stale after a write."""
from unittest.mock import MagicMock, patch

import pytest

from services import card_cache
from services import search as S
from tests import search_golden

pytestmark = pytest.mark.card_snapshot


def _golden(with_snapshot: bool):
    if with_snapshot:
        return search_golden.evaluate()
    with patch.object(card_cache, "snapshot", lambda: None):
        return search_golden.evaluate()


def test_the_snapshot_gives_the_golden_set_the_same_answers_as_the_database_path():
    for a, b in zip(_golden(False), _golden(True)):
        card_cache.invalidate()
        assert a.top == b.top, a.target
        assert all(abs(a.scores[h] - b.scores[h]) <= 0.002 for h in a.top), a.target


def _corpus(monkeypatch, rows):
    reads = []
    sb = MagicMock()
    sb.rpc.side_effect = AssertionError("a search with the snapshot must not call the database functions")
    monkeypatch.setattr(S.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(S, "embed_text", search_golden.hash_embed)
    monkeypatch.setattr(S, "SEM_FLOOR", search_golden.HASH_SEM_FLOOR)
    monkeypatch.setattr(S, "SEM_SPAN", search_golden.HASH_SEM_SPAN)

    def published(**kw):
        reads.append(kw)
        return rows
    monkeypatch.setattr(S.cards_service, "list_published_rows", published)
    return reads


def test_a_relaxed_search_reads_the_cards_once(monkeypatch):
    reads = _corpus(monkeypatch, search_golden.build_rows(search_golden.load()))
    found = S.search_agents(q="seed investor in Paris", role="investor", location="Paris", relax=True,
                            include_unclaimed=True, limit=5)
    assert found and len(reads) == 1
    S.search_agents(q="rust engineer", role="engineer", include_unclaimed=True)
    assert len(reads) == 1, "a second search within the TTL reads nothing"


def test_a_write_clears_the_snapshot(monkeypatch):
    rows = search_golden.build_rows(search_golden.load())
    reads = _corpus(monkeypatch, rows)
    S.search_agents(q="rust engineer", include_unclaimed=True)
    card_cache.invalidate()
    S.search_agents(q="rust engineer", include_unclaimed=True)
    assert len(reads) == 2


def test_unclaimed_cards_stay_out_unless_asked_for(monkeypatch):
    rows = search_golden.build_rows(search_golden.load())
    rows[0] = {**rows[0], "owner_email": ""}
    _corpus(monkeypatch, rows)
    handle = rows[0]["handle"]
    assert handle not in {r["handle"] for r in S.search_agents(q=handle.replace("_", " "), limit=50)}


def test_too_many_cards_fall_back_to_the_database(monkeypatch):
    monkeypatch.setattr(card_cache, "SNAPSHOT_MAX_CARDS", 3)
    rows = search_golden.build_rows(search_golden.load())
    monkeypatch.setattr(S.cards_service, "list_published_rows", lambda **kw: rows)
    assert card_cache.snapshot() is None


def test_unit_vectors_make_cosine_a_dot_product():
    a, b = card_cache.unit([3.0, 4.0]), card_cache.unit("[4.0, 3.0]")
    assert a == [0.6, 0.8] and abs(card_cache.dot(a, b) - 0.96) < 1e-9
    assert card_cache.unit([0.0, 0.0]) == [] and card_cache.dot([], b) is None
    assert card_cache.unit("not json") == []


def test_a_repeated_query_is_embedded_once(monkeypatch):
    _corpus(monkeypatch, search_golden.build_rows(search_golden.load()))
    calls = []
    monkeypatch.setattr(S, "embed_text", lambda q: calls.append(q) or search_golden.hash_embed(q))
    S.search_agents(q="seed investor in Paris", role="investor", relax=True, include_unclaimed=True)
    S.search_agents(q="seed investor in Paris", role="investor", include_unclaimed=True)   # memory's retry
    assert calls == ["seed investor in Paris"]


def test_a_name_lookup_reads_the_snapshot(monkeypatch):
    from services import lookup
    rows = search_golden.build_rows(search_golden.load())
    reads = _corpus(monkeypatch, rows)
    found = lookup.lookup_by_name("chandan", 5, include_unclaimed=True)
    assert found and found[0]["handle"] == "chandan_kumar" and len(reads) == 1


def test_an_old_copy_keeps_serving_while_a_new_one_loads(monkeypatch):
    import threading
    rows = search_golden.build_rows(search_golden.load())
    reads = _corpus(monkeypatch, rows)
    first = card_cache.snapshot()
    monkeypatch.setattr(card_cache, "SNAPSHOT_TTL_SECONDS", 0.0)
    started = threading.Event()
    real_load = card_cache._load
    monkeypatch.setattr(card_cache, "_load", lambda: (started.set(), real_load())[1])
    assert card_cache.snapshot() is first, "past the TTL the old copy answers at once"
    assert started.wait(2)
    for _ in range(100):                     # the background load replaces it
        if card_cache._snapshot is not first and card_cache._snapshot is not None:
            break
        threading.Event().wait(0.01)
    assert card_cache._snapshot is not first and len(reads) == 2


def test_a_load_that_overlapped_a_write_is_not_kept(monkeypatch):
    rows = search_golden.build_rows(search_golden.load())
    _corpus(monkeypatch, rows)
    real_load = card_cache._load
    monkeypatch.setattr(card_cache, "_load", lambda: (card_cache.invalidate(), real_load())[1])
    assert card_cache.snapshot() is not None       # this caller gets an answer
    assert card_cache._snapshot is None            # but the next search reads again
