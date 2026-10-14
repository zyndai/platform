"""Public working_on / can_help_with are derived from live memory facts."""
from datetime import datetime, timedelta, timezone

from models.card import AgentProfileCard
from services import cards as cards_service
from services.card_view import build_card_view
from services.signals import derive_public_signals, merge_unique

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _fact(predicate, obj, days_ago=1, confidence=0.9):
    return {"predicate": predicate, "object": obj, "confidence": confidence,
            "approved_at": (NOW - timedelta(days=days_ago)).isoformat()}


def _card(**kw):
    base = dict(id="c1", handle="h", working_on=["Agent tooling"], can_help_with=["Code review"])
    base.update(kw)
    return AgentProfileCard(**base)


def test_memory_first_then_stored_deduped_case_insensitively():
    card = _card(zynd_memory=[_fact("is_working_on", "LinkedIn outreach"),
                              _fact("is_working_on", "agent tooling")])
    out = derive_public_signals(card, NOW)
    assert out.working_on == ["LinkedIn outreach", "agent tooling"]  # stored "Agent tooling" is the dup


def test_newest_working_on_comes_first_and_is_capped():
    facts = [_fact("is_working_on", f"Stream {i}", days_ago=i) for i in range(1, 8)]
    out = derive_public_signals(_card(zynd_memory=facts, working_on=[]), NOW)
    assert out.working_on == ["Stream 1", "Stream 2", "Stream 3", "Stream 4"]


def test_expired_working_on_falls_back_to_the_stored_list():
    # is_working_on lives 14 days; a 30 day old approval no longer counts.
    card = _card(zynd_memory=[_fact("is_working_on", "Old stream", days_ago=30)])
    out = derive_public_signals(card, NOW)
    assert out.working_on == ["Agent tooling"]


def test_can_help_with_prefers_confident_expertise():
    card = _card(zynd_memory=[_fact("has_expertise_in", "Low", confidence=0.5),
                              _fact("has_expertise_in", "High", confidence=0.95)])
    assert derive_public_signals(card, NOW).can_help_with == ["High", "Low", "Code review"]


def test_no_memory_returns_the_card_untouched():
    card = _card()
    assert derive_public_signals(card, NOW) is card
    assert derive_public_signals(_card(zynd_memory=[]), NOW).working_on == ["Agent tooling"]


def test_other_predicates_do_not_leak_into_the_lists():
    card = _card(zynd_memory=[_fact("is_building", "Verusa"), _fact("uses_tool", "Codex"),
                              _fact("is_learning", "Rust")])
    out = derive_public_signals(card, NOW)
    assert out.working_on == ["Agent tooling"] and out.can_help_with == ["Code review"]


def test_the_stored_card_is_never_mutated():
    # The editor saves what it loaded; derived items must not be written back.
    card = _card(zynd_memory=[_fact("is_working_on", "LinkedIn outreach")])
    derive_public_signals(card, NOW)
    assert card.working_on == ["Agent tooling"]


def test_merge_unique_skips_blanks_and_non_strings():
    assert merge_unique(["", " A ", "a"], ["B", None, "b"], 5) == ["A", "B"]  # type: ignore[list-item]


def _fresh(predicate, obj):
    """Approved just now by the real clock, for paths that do not take a `now`."""
    return {"predicate": predicate, "object": obj, "confidence": 0.9,
            "approved_at": datetime.now(timezone.utc).isoformat()}


def test_public_payload_is_derived():
    row = {"card": _card(zynd_memory=[_fresh("is_working_on", "LinkedIn outreach")]).model_dump(mode="json"),
           "handle": "h"}
    payload = cards_service._public_card_payload(row)
    assert payload["working_on"][0] == "LinkedIn outreach"


def test_agent_view_is_derived():
    view = build_card_view(_card(zynd_memory=[_fresh("has_expertise_in", "Compliance")]), claimed=True)
    assert view.can_help_with[0] == "Compliance"


# ── HTTP routes: the public read is derived, the owner's editor read is not ────────

import pytest
from fastapi.testclient import TestClient

import api.cards as cards_api
import config
from api.auth import Principal
from main import app


class _Resp:
    def __init__(self, data):
        self.data = data


@pytest.fixture
def client():
    return TestClient(app)


def _stored_card_with_memory():
    return _card(zynd_memory=[_fresh("is_working_on", "LinkedIn outreach"),
                              _fresh("has_expertise_in", "Compliance engineering")])


def test_public_by_handle_route_serves_the_derived_lists(client, monkeypatch):
    row = {"card": _stored_card_with_memory().model_dump(mode="json"), "handle": "alice", "alias": None}
    monkeypatch.setattr(config, "get_supabase", lambda: object())
    monkeypatch.setattr(cards_service, "_select_public", lambda sb, build: _Resp([row]))

    body = client.get("/cards/by-handle/alice").json()

    assert body["working_on"] == ["LinkedIn outreach", "Agent tooling"]
    assert body["can_help_with"] == ["Compliance engineering", "Code review"]


def test_owner_editor_read_is_never_derived(client, monkeypatch):
    # The editor saves what it loaded. If derived items were in /mine, deleting one in the
    # editor and saving would be undone by memory on the next read.
    principal = Principal(email="alice@example.com", sub="s", iss="https://x/auth/v1")
    monkeypatch.setattr(cards_api, "verify_supabase_jwt", lambda auth: principal)
    monkeypatch.setattr(cards_service, "get_card_by_owner",
                        lambda email: (_stored_card_with_memory(), "alice"))

    body = client.get("/cards/mine", headers={"Authorization": "Bearer x"}).json()

    assert body["card"]["working_on"] == ["Agent tooling"]
    assert body["card"]["can_help_with"] == ["Code review"]
