"""
Tests for services/zynd_memory.py — memory-layer fetch + card refresh cron.
Network and Supabase are mocked. Run: python -m pytest tests/test_zynd_memory.py -v
"""
import asyncio
from unittest.mock import MagicMock

import pytest

import config
from models.card import AgentProfileCard
from services import cards as cards_service
from services import zynd_memory


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "svc-token")
    monkeypatch.setattr(config, "MEMORY_LAYER_URL", "https://api.zynd.ai")
    monkeypatch.setattr(config, "MEMORY_REFRESH_INTERVAL_HOURS", 6)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _fake_get(status=200, payload=None, exc=None):
    def fake_get(url, headers=None, timeout=None):
        if exc:
            raise exc
        return _Resp(status, payload)

    return fake_get


def test_fetch_builds_url_and_auth_header(monkeypatch):
    seen = {}
    payload = {"connected": True, "facts": []}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Resp(200, payload)

    monkeypatch.setattr(zynd_memory.httpx, "get", fake_get)
    out = zynd_memory.fetch_findability("Alice@Example.com")

    assert out == payload
    assert seen["url"] == "https://api.zynd.ai/v1/service/findability/Alice%40Example.com"
    assert seen["headers"]["Authorization"] == "Bearer svc-token"


def test_fetch_returns_payload_on_success(monkeypatch):
    payload = {"connected": True, "facts": [{"predicate": "is_building", "object": "micro-SaaS"}]}
    monkeypatch.setattr(zynd_memory.httpx, "get", _fake_get(200, payload))
    assert zynd_memory.fetch_findability("alice@example.com") == payload


def test_fetch_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(zynd_memory.httpx, "get", _fake_get(401, None))
    assert zynd_memory.fetch_findability("alice@example.com") is None


def test_fetch_returns_none_on_network_error(monkeypatch):
    monkeypatch.setattr(zynd_memory.httpx, "get", _fake_get(exc=RuntimeError("boom")))
    assert zynd_memory.fetch_findability("alice@example.com") is None


def test_fetch_disabled_without_token(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "")
    monkeypatch.setattr(zynd_memory.httpx, "get", _fake_get(200, {"connected": True, "facts": []}))
    assert zynd_memory.fetch_findability("alice@example.com") is None


def test_fetch_rejects_blank_email(monkeypatch):
    monkeypatch.setattr(zynd_memory.httpx, "get", _fake_get(200, {"connected": True, "facts": []}))
    assert zynd_memory.fetch_findability("   ") is None


# ── update_card_memory (services/cards.py) ───────────────────────────────────

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self.payload = None

    def select(self, *args):
        return self

    def eq(self, *args, **kwargs):
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return MagicMock(data=self._rows)


def _card_json(zynd_memory=None):
    return {
        "id": "abc123", "status": "published", "handle": "alice",
        "identity": {"name": "Alice", "headline": "", "location": "", "avatar_url": "", "links": {}},
        "summary": "Engineer.", "zynd_memory": zynd_memory,
    }


def _mock_sb(monkeypatch, rows):
    query = _FakeQuery(rows)
    sb = MagicMock()
    sb.table.return_value = query
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    return query


def test_update_card_memory_sets_snapshot(monkeypatch):
    query = _mock_sb(monkeypatch, [{"card": _card_json()}])
    facts = [{"predicate": "is_building", "object": "micro-SaaS"}]
    monkeypatch.setattr("services.embed.embed_text", lambda text: [0.1, 0.2])

    assert cards_service.update_card_memory("alice", facts) is True
    assert query.payload["card"]["zynd_memory"] == facts
    assert query.payload["embedding"] == [0.1, 0.2]
    assert query.payload["card"]["summary"] == "Engineer."  # rest of card preserved


def test_update_card_memory_clears_snapshot(monkeypatch):
    query = _mock_sb(monkeypatch, [{"card": _card_json([{"predicate": "is_building", "object": "old"}])}])

    assert cards_service.update_card_memory("alice", None) is True
    assert query.payload["card"]["zynd_memory"] is None


def test_update_card_memory_writes_empty_list(monkeypatch):
    query = _mock_sb(monkeypatch, [{"card": _card_json([{"predicate": "is_building", "object": "old"}])}])

    assert cards_service.update_card_memory("alice", []) is True
    assert query.payload["card"]["zynd_memory"] == []


def test_update_card_memory_missing_handle(monkeypatch):
    query = _mock_sb(monkeypatch, [])

    assert cards_service.update_card_memory("ghost", []) is False
    assert query.payload is None


# ── refresh_all_cards_memory ─────────────────────────────────────────────────

def _row(handle, email, zynd_memory=None):
    return {"card": _card_json(zynd_memory), "handle": handle, "owner_email": email}


def test_refresh_cycle_updates_changed_cards(monkeypatch):
    facts = [{"predicate": "is_building", "object": "micro-SaaS"}]
    monkeypatch.setattr(
        cards_service, "list_published_rows",
        lambda **kw: [_row("alice", "alice@example.com"), _row("bob", "bob@example.com", facts)],
    )
    monkeypatch.setattr(
        cards_service, "_row_to_card",
        lambda row: AgentProfileCard.model_validate(row["card"]),
    )
    calls = []
    monkeypatch.setattr(
        cards_service, "update_card_memory",
        lambda handle, f: calls.append((handle, f)) or True,
    )
    monkeypatch.setattr(zynd_memory, "fetch_findability", lambda email: {"connected": True, "facts": facts})

    stats = asyncio.run(zynd_memory.refresh_all_cards_memory())

    assert stats["updated"] == 1     # alice got the facts
    assert stats["unchanged"] == 1   # bob already had them
    assert calls == [("alice", facts)]


def test_refresh_cycle_clears_revoked_facts(monkeypatch):
    old = [{"predicate": "is_building", "object": "old"}]
    monkeypatch.setattr(
        cards_service, "list_published_rows",
        lambda **kw: [_row("alice", "alice@example.com", old)],
    )
    monkeypatch.setattr(
        cards_service, "_row_to_card",
        lambda row: AgentProfileCard.model_validate(row["card"]),
    )
    calls = []
    monkeypatch.setattr(
        cards_service, "update_card_memory",
        lambda handle, f: calls.append((handle, f)) or True,
    )
    monkeypatch.setattr(zynd_memory, "ping_revalidate", lambda handle: None)
    monkeypatch.setattr(zynd_memory, "fetch_findability", lambda email: {"connected": True, "facts": []})

    stats = asyncio.run(zynd_memory.refresh_all_cards_memory())

    assert stats["updated"] == 1
    assert calls == [("alice", [])]


def test_snapshot_from_payload_distinguishes_empty():
    assert zynd_memory.snapshot_from_payload(None) is None
    assert zynd_memory.snapshot_from_payload({"connected": False, "facts": []}) is None
    assert zynd_memory.snapshot_from_payload({"connected": True, "facts": []}) == []
    assert zynd_memory.snapshot_from_payload({"connected": True}) == []


def test_refresh_cycle_skips_cards_without_email(monkeypatch):
    monkeypatch.setattr(cards_service, "list_published_rows", lambda **kw: [_row("alice", "")])
    monkeypatch.setattr(zynd_memory, "fetch_findability", lambda email: {"connected": True, "facts": []})
    stats = asyncio.run(zynd_memory.refresh_all_cards_memory())

    assert stats["no_email"] == 1
    assert stats["updated"] == 0


def test_refresh_cycle_keeps_snapshot_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(cards_service, "list_published_rows", lambda **kw: [_row("alice", "alice@example.com")])
    monkeypatch.setattr(cards_service, "_row_to_card", lambda row: AgentProfileCard.model_validate(row["card"]))
    monkeypatch.setattr(cards_service, "update_card_memory", lambda handle, f: True)
    monkeypatch.setattr(zynd_memory, "fetch_findability", lambda email: None)  # memory layer down

    stats = asyncio.run(zynd_memory.refresh_all_cards_memory())

    assert stats["errors"] == 1
    assert stats["updated"] == 0
