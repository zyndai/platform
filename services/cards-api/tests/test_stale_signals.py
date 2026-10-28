"""Stale "Working on": freshness rules, the owner's confirm endpoint, and the digest nudge."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import config
from api import owner_home as routes
from models.card import AgentProfileCard
from services import digest as digest_service
from services import stale_signals
from services.card_view import build_card_view
from services.signals import derive_public_signals

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def card(**kwargs):
    return AgentProfileCard(id="c1", handle="alice", **{"working_on": ["Zynd Cards"], **kwargs})


# ── freshness rules ──

def test_legacy_card_without_a_stamp_is_never_stale():
    # #given a card from before migration 0033: Working on set, no stamp
    legacy = card()
    # #then unknown reads as fresh, however old the card is
    assert stale_signals.working_on_is_stale(legacy, NOW) is False


@pytest.mark.parametrize("age_days, stale", [(0, False), (89, False), (90, True), (400, True)])
def test_stale_after_ninety_days(age_days, stale):
    c = card(working_on_updated_at=NOW - timedelta(days=age_days))
    assert stale_signals.working_on_is_stale(c, NOW) is stale


def test_empty_working_on_has_nothing_to_go_stale():
    c = card(working_on=["", "  "], working_on_updated_at=NOW - timedelta(days=400))
    assert stale_signals.working_on_is_stale(c, NOW) is False


def test_live_memory_fact_makes_the_public_list_fresh():
    # #given an old stored stamp, but memory approved a new "is_working_on" two days ago
    approved = NOW - timedelta(days=2)
    c = card(working_on_updated_at=NOW - timedelta(days=200),
             zynd_memory=[{"predicate": "is_working_on", "object": "Agent search", "approved_at": approved.isoformat()}])
    # #when the public card is derived
    public = derive_public_signals(c, NOW)
    # #then its stamp is the newest source, and it is not stale
    assert public.working_on_updated_at == approved
    assert stale_signals.working_on_is_stale(public, NOW) is False


def test_memory_fact_from_the_future_cannot_pin_the_list_fresh():
    c = card(zynd_memory=[{"predicate": "is_working_on", "object": "X", "approved_at": (NOW + timedelta(days=1)).isoformat()}])
    assert derive_public_signals(c, NOW).working_on_updated_at == NOW


def test_stamp_reaches_the_card_view():
    stamp = NOW - timedelta(days=100)
    assert build_card_view(card(working_on_updated_at=stamp), claimed=True).working_on_updated_at == stamp


def test_unknown_stamp_is_not_written_into_the_stored_card_json():
    # cards-api stores model_dump() as the card JSON: legacy cards must not gain a null key.
    assert "working_on_updated_at" not in card().model_dump(mode="json")
    assert card(working_on_updated_at=NOW).model_dump(mode="json")["working_on_updated_at"] == "2026-10-28T12:00:00Z"


@pytest.mark.parametrize("junk", ["not a date", 12, {"a": 1}, ""])
def test_junk_stamp_reads_as_unknown_instead_of_failing_the_card(junk):
    assert card(working_on_updated_at=junk).working_on_updated_at is None


def test_full_card_writes_never_send_the_column(monkeypatch):
    # #given a card read back with a (possibly outdated) mirrored stamp
    from services import cards
    stale_copy = card(working_on_updated_at=NOW - timedelta(days=300))
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "update", "upsert"):
        getattr(q, method).return_value = q
    q.execute.return_value.data = [{"owner_email": "alice@example.com", "claim_token_hash": None}]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards.embed, "embed_text", lambda _t: None)
    monkeypatch.setattr(cards, "_assign_handle", lambda *a: "alice")
    # #when the publish upsert and the editor's full-card PATCH write it
    cards.insert_card(stale_copy, None, None, owner_email="alice@example.com")
    cards.update_card("alice", stale_copy, "alice@example.com")
    # #then only the card JSON carries it (the 0033 trigger rewrites that mirror from the column);
    # the column itself is never in a payload, so these writes cannot move the stamp
    payloads = [c.args[0] for c in q.upsert.call_args_list + q.update.call_args_list]
    assert len(payloads) == 2
    for payload in payloads:
        assert "working_on_updated_at" not in payload


# ── confirm endpoint ──

class _Table:
    """agent_profile_cards for one owner row; records the update payload."""

    def __init__(self, row, update_error=None):
        self.row, self.update_error = row, update_error
        self.updates: list[dict] = []
        self._op = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self.updates.append(payload)
        return self

    def eq(self, *_a):
        return self

    def neq(self, *_a):
        return self

    def ilike(self, _col, value):
        self._owner_like = value
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self._op == "update" and self.update_error:
            raise self.update_error
        return SimpleNamespace(data=[self.row] if self.row else [])


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S10_HOME", True)
    monkeypatch.setattr(config, "FEATURE_STALE_SIGNALS", True)
    monkeypatch.setattr(routes, "ping_revalidate", lambda *a, **k: None)
    principals = {"Bearer owner": "alice@example.com", "Bearer other": "mallory@example.com"}

    def principal(auth):
        if auth not in principals:
            raise routes.HTTPException(401, "Unauthorized")
        return SimpleNamespace(email=principals[auth])

    monkeypatch.setattr(routes, "_principal", principal)
    table = _Table({"id": "c1", "owner_email": "Alice@Example.com", "status": "published"})
    sb = MagicMock()
    sb.table.return_value = table
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    return SimpleNamespace(client=TestClient(app), table=table)


URL = "/cards/by-handle/alice/working-on/confirm"


def test_confirm_requires_sign_in(api):
    assert api.client.post(URL).status_code == 401
    assert api.table.updates == []


def test_confirm_refuses_someone_elses_card(api):
    res = api.client.post(URL, headers={"Authorization": "Bearer other"})
    assert res.status_code == 403
    assert api.table.updates == []


def test_owner_confirm_resets_only_the_stamp(api):
    res = api.client.post(URL, headers={"Authorization": "Bearer owner"})
    assert res.status_code == 200
    assert list(api.table.updates[0]) == ["working_on_updated_at"]
    assert res.json()["working_on_updated_at"] == api.table.updates[0]["working_on_updated_at"]


def test_confirm_unknown_card_is_404(api):
    api.table.row = None
    assert api.client.post(URL, headers={"Authorization": "Bearer owner"}).status_code == 404


def test_confirm_before_migration_is_503_not_500(api):
    api.table.update_error = APIError({"code": "PGRST204", "message": "Could not find the 'working_on_updated_at' column"})
    assert api.client.post(URL, headers={"Authorization": "Bearer owner"}).status_code == 503


def test_confirm_other_database_errors_are_not_hidden(api):
    api.table.update_error = APIError({"code": "57014", "message": "canceling statement due to statement timeout"})
    with pytest.raises(APIError):
        api.client.post(URL, headers={"Authorization": "Bearer owner"})


def test_confirm_is_hidden_while_the_flag_is_off(api, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_STALE_SIGNALS", False)
    assert api.client.post(URL, headers={"Authorization": "Bearer owner"}).status_code == 404
    assert api.table.updates == []


# ── digest ──

def _row(stamp_days_ago: int | None) -> dict:
    data = card(**({"working_on_updated_at": NOW - timedelta(days=stamp_days_ago)} if stamp_days_ago is not None else {}))
    return {"handle": "alice", "owner_email": "alice@example.com", "card": data.model_dump(mode="json")}


def _digest(monkeypatch, row: dict, flag: bool) -> tuple[str, str]:
    monkeypatch.setattr(config, "FEATURE_STALE_SIGNALS", flag)
    monkeypatch.setattr(config, "FEATURE_S10_HOME", False)    # owner_home blocks are out of scope here
    extras = digest_service._owner_extras(row, [row], NOW, NOW)
    return (digest_service.render_digest("alice", None, None, name="Alice", extras=extras),
            digest_service.render_digest_html("alice", None, None, name="Alice", extras=extras))


def test_digest_nudges_a_stale_working_on(monkeypatch):
    text, html = _digest(monkeypatch, _row(120), flag=True)
    assert "WORKING ON" in text and "Unchanged for 3+ months." in text
    assert "/p/alice#working-on" in text and "/p/alice/edit#signals" in text
    assert "Still working on this?" in html and ">Confirm<" in html and ">Update it<" in html
    assert "/p/alice#working-on" in html and "/p/alice/edit#signals" in html


@pytest.mark.parametrize("stamp_days_ago, flag", [(120, False), (10, True), (None, True)])
def test_digest_line_only_when_stale_and_flag_on(monkeypatch, stamp_days_ago, flag):
    text, html = _digest(monkeypatch, _row(stamp_days_ago), flag=flag)
    assert "WORKING ON" not in text
    assert "Still working on this?" not in html


def test_digest_with_flag_off_is_unchanged(monkeypatch):
    row = _row(120)
    on_text, on_html = _digest(monkeypatch, row, flag=False)
    monkeypatch.setattr(config, "FEATURE_STALE_SIGNALS", False)
    extras = {"date": "Wed, 28 Oct"}
    assert on_text == digest_service.render_digest("alice", None, None, name="Alice", extras=extras)
    assert on_html == digest_service.render_digest_html("alice", None, None, name="Alice", extras=extras)


def test_digest_survives_an_unreadable_card(monkeypatch):
    row = {"handle": "alice", "owner_email": "alice@example.com", "card": {"skills": "not a list"}}
    text, _html = _digest(monkeypatch, row, flag=True)
    assert "WORKING ON" not in text
