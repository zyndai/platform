"""Search reads one in-process copy of the published cards (services/card_cache.py). Most tests
fake the database per test and check the database path, so the copy is off by default and never
outlives a test; tests/test_card_cache.py turns it on."""
import pytest

from services import card_cache, search, trust


@pytest.fixture(autouse=True)
def _no_card_snapshot(request, monkeypatch):
    card_cache.invalidate()
    trust._verified_cache.clear()
    search._query_vectors.clear()
    if "card_snapshot" not in request.keywords:
        monkeypatch.setattr(card_cache, "snapshot", lambda: None)
    yield
    card_cache.invalidate()


def pytest_configure(config):
    config.addinivalue_line("markers", "card_snapshot: let search use the in-process card snapshot")
