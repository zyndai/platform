"""About draft from memory: what reaches the model, what is rejected, and that nothing is saved."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.cards as cards_api
import config
from api.auth import Principal
from main import app
from models.card import AgentProfileCard
from services import cards as cards_service
from services import summary_draft as sd


def _fresh(predicate, obj, **extra):
    return {"predicate": predicate, "object": obj, "confidence": 0.9,
            "approved_at": datetime.now(timezone.utc).isoformat(), **extra}


def _card(**kw):
    base = dict(
        id="c1", handle="alice", identity={"name": "Alice Chen", "headline": "Founder"},
        summary="Seasoned engineer.",
        work_experience=[{"title": "Co-Founder", "company": "Verusa", "end_date": ""},
                         {"title": "Engineer", "company": "OldCo", "end_date": "2023"}],
        zynd_memory=[_fresh("is_building", "Verusa"),
                     _fresh("is_working_on", "LinkedIn outreach"),
                     _fresh("has_expertise_in", "Compliance engineering"),
                     _fresh("uses_tool", "Codex"),
                     _fresh("is_building", "verusa"),
                     _fresh("believes", "private opinion")],
    )
    base.update(kw)
    return AgentProfileCard(**base)


def test_prompt_uses_only_public_facts_grouped_and_deduped():
    sections = sd.facts_by_section(_card())
    assert sections == {
        "Building": ["Verusa"],
        "Working on right now": ["LinkedIn outreach"],
        "Expert in": ["Compliance engineering"],
        "Tools they use": ["Codex"],
    }
    user = sd.build_messages(_card(), sections)[1]["content"]
    assert "Current role: Co-Founder at Verusa" in user
    assert "OldCo" not in user  # past roles are not current
    assert "private opinion" not in user  # non-card predicates never reach the model


def test_evidence_text_never_reaches_the_prompt():
    card = _card(zynd_memory=[_fresh("uses_tool", "Codex", evidence="SECRET sentence from chat")])
    user = sd.build_messages(card, sd.facts_by_section(card))[1]["content"]
    assert "SECRET" not in user


def test_expired_working_on_is_left_out():
    old = {"predicate": "is_working_on", "object": "Stale", "confidence": 0.9,
           "approved_at": "2020-01-01T00:00:00+00:00"}
    assert "Working on right now" not in sd.facts_by_section(_card(zynd_memory=[old]))


@pytest.mark.parametrize("bad", [
    "", "   ", "See https://evil.example for more", "Reach me at a@b.com",
    "A passionate builder of things.", "x" * 701,
])
def test_unusable_drafts_are_rejected(bad):
    with pytest.raises(sd.DraftRejected):
        sd.clean_draft(bad)


def test_clean_draft_collapses_whitespace_and_strips_quotes():
    assert sd.clean_draft('  "Alice builds Verusa.\n  She works on outreach."  ') == \
        "Alice builds Verusa. She works on outreach."


def test_based_on_lists_what_the_draft_came_from():
    assert sd.based_on({"Building": ["Verusa"], "Expert in": ["A", "B"]}) == \
        ["Building: Verusa", "Expert in: A, B"]


# ── route ───────────────────────────────────────────────────────────────────────

PRINCIPAL = Principal(email="alice@example.com", sub="s", iss="https://x/auth/v1")


class _Client:
    def __init__(self, text):
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.calls += 1
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

        self.chat = SimpleNamespace(completions=_Completions())


@pytest.fixture
def client(monkeypatch):
    cards_api._last_draft_at.clear()
    monkeypatch.setattr(cards_api, "verify_supabase_jwt", lambda auth: PRINCIPAL)
    saved = []
    monkeypatch.setattr(cards_service, "update_card", lambda *a, **k: saved.append(a) or None)
    c = TestClient(app)
    c.saved = saved
    return c


def _owner(monkeypatch, card):
    monkeypatch.setattr(cards_service, "get_card_by_owner", lambda email: (card, "alice"))


def test_requires_auth(monkeypatch):
    monkeypatch.setattr(cards_api, "verify_supabase_jwt", lambda auth: None)
    assert TestClient(app).post("/cards/mine/summary-draft").status_code == 401


def test_returns_a_preview_and_saves_nothing(client, monkeypatch):
    _owner(monkeypatch, _card())
    llm = _Client("Alice Chen builds Verusa and works on LinkedIn outreach.")
    monkeypatch.setattr(config, "get_llm_client", lambda: llm)

    r = client.post("/cards/mine/summary-draft", headers={"Authorization": "Bearer x"})

    assert r.status_code == 200
    assert r.json()["draft"] == "Alice Chen builds Verusa and works on LinkedIn outreach."
    assert "Building: Verusa" in r.json()["based_on"]
    assert client.saved == []  # a draft is never written to the card


def test_no_approved_memory_is_a_clear_422_and_never_calls_the_model(client, monkeypatch):
    _owner(monkeypatch, _card(zynd_memory=[]))
    llm = _Client("should not be used")
    monkeypatch.setattr(config, "get_llm_client", lambda: llm)
    r = client.post("/cards/mine/summary-draft", headers={"Authorization": "Bearer x"})
    assert r.status_code == 422 and llm.calls == 0


def test_bad_model_output_is_a_502_not_shown(client, monkeypatch):
    _owner(monkeypatch, _card())
    monkeypatch.setattr(config, "get_llm_client", lambda: _Client("Visit https://spam.example"))
    r = client.post("/cards/mine/summary-draft", headers={"Authorization": "Bearer x"})
    assert r.status_code == 502 and "spam" not in r.text


def test_model_outage_is_a_502(client, monkeypatch):
    _owner(monkeypatch, _card())

    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(config, "get_llm_client", boom)
    assert client.post("/cards/mine/summary-draft",
                       headers={"Authorization": "Bearer x"}).status_code == 502


def test_rapid_repeat_is_rate_limited(client, monkeypatch):
    _owner(monkeypatch, _card())
    monkeypatch.setattr(config, "get_llm_client", lambda: _Client("Alice builds Verusa."))
    h = {"Authorization": "Bearer x"}
    assert client.post("/cards/mine/summary-draft", headers=h).status_code == 200
    assert client.post("/cards/mine/summary-draft", headers=h).status_code == 429
