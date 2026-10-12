"""
S03 unclaimed-card tiering + S14 honest chat prompt.

Claim-by-LinkedIn matching, takedown hiding, owner_email never appearing in
public responses, agent-endpoint default exclusion, and the chat prompt that
discloses it is an AI assistant.
"""
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api import agents as agents_api
from api import ask as ask_api
from api import cards as cards_api
from api import chat as chat_api
from api.auth import Principal
from models.card import AgentProfileCard
from services import cards as cards_service


def _card_json(handle="alice", linkedin="https://www.linkedin.com/in/alice-engineer/") -> dict:
    return AgentProfileCard(
        id="cid1",
        status="published",
        handle=handle,
        identity={"name": "Alice", "headline": "Engineer", "location": "Pune", "avatar_url": "",
                  "links": {"linkedin": linkedin}},
        summary="Engineer.",
    ).model_dump(mode="json")


# ── claim by LinkedIn match ─────────────────────────────────────────

def test_claim_card_by_owner_matching_linkedin(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("owner_email,claim_token_hash,card,status").eq("handle", "alice").execute.return_value = MagicMock(
        data=[{"owner_email": None, "claim_token_hash": "h", "card": _card_json()}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    principal = Principal("alice@example.com", "sub", "iss", user_metadata={"preferred_username": "alice-engineer"})
    claimed, msg = cards_service.claim_card_by_owner("alice", principal)

    assert claimed is True
    update = sb.table("agent_profile_cards").update
    update.assert_called_once()
    assert update.call_args.args[0]["owner_email"] == "alice@example.com"
    assert update.call_args.args[0]["claim_token_hash"] is None


def test_claim_card_by_owner_refuses_mismatched_linkedin(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("owner_email,claim_token_hash,card,status").eq("handle", "alice").execute.return_value = MagicMock(
        data=[{"owner_email": None, "claim_token_hash": "h", "card": _card_json()}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    principal = Principal("mallory@example.com", "sub", "iss", user_metadata={"preferred_username": "mallory"})
    claimed, msg = cards_service.claim_card_by_owner("alice", principal)

    assert claimed is False
    assert "does not match" in msg
    sb.table("agent_profile_cards").update.assert_not_called()


def test_claim_card_by_owner_refuses_when_card_has_no_linkedin(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("owner_email,claim_token_hash,card,status").eq("handle", "alice").execute.return_value = MagicMock(
        data=[{"owner_email": None, "claim_token_hash": "h", "card": _card_json(linkedin="")}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    principal = Principal("alice@example.com", "sub", "iss", user_metadata={"preferred_username": "alice"})
    claimed, msg = cards_service.claim_card_by_owner("alice", principal)

    assert claimed is False
    assert "no LinkedIn" in msg


def test_claim_card_by_owner_refuses_already_claimed(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("owner_email,claim_token_hash,card,status").eq("handle", "alice").execute.return_value = MagicMock(
        data=[{"owner_email": "someone@example.com", "claim_token_hash": None, "card": _card_json()}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    principal = Principal("alice@example.com", "sub", "iss", user_metadata={"preferred_username": "alice-engineer"})
    claimed, msg = cards_service.claim_card_by_owner("alice", principal)

    assert claimed is False
    assert "already claimed" in msg


# ── takedown ────────────────────────────────────────────────────────

def test_request_takedown_hides_card_and_records(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("id").eq("handle", "alice").eq("status", "published").execute.return_value = MagicMock(
        data=[{"id": "cid1"}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    ok = cards_service.request_takedown("alice", "sub-x", "this is not me")

    assert ok is True
    sb.table("takedown_requests").insert.assert_called_once()
    inserted = sb.table("takedown_requests").insert.call_args.args[0]
    assert inserted["handle"] == "alice"
    assert inserted["status"] == "pending"
    sb.table("agent_profile_cards").update.assert_called_once()
    assert sb.table("agent_profile_cards").update.call_args.args[0] == {"status": "takedown_requested"}


def test_request_takedown_missing_card_returns_false(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("id").eq("handle", "ghost").eq("status", "published").execute.return_value = MagicMock(data=[])
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    assert cards_service.request_takedown("ghost", None, None) is False


# ── owner_email never public ────────────────────────────────────────

def test_public_card_responses_never_expose_owner_email(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("card,handle,owner_email").eq("handle", "alice").eq("status", "published").execute.return_value = MagicMock(
        data=[{"card": _card_json(), "handle": "alice", "owner_email": "alice@example.com"}]
    )
    monkeypatch.setattr(cards_api.cards_service.config, "get_supabase", lambda: sb)

    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")
    client = TestClient(app)

    resp = client.get("/cards/by-handle/alice")
    assert resp.status_code == 200
    assert resp.json()["claimed"] is True
    assert "owner_email" not in resp.json()


def test_public_list_never_exposes_owner_email(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("card,handle,owner_email").eq("status", "published").order("created_at", desc=True).limit(1000).execute.return_value = MagicMock(
        data=[
            {"card": _card_json("alice"), "handle": "alice", "owner_email": "alice@example.com"},
            {"card": _card_json("bob"), "handle": "bob", "owner_email": None},
        ]
    )
    monkeypatch.setattr(cards_api.cards_service.config, "get_supabase", lambda: sb)

    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")
    client = TestClient(app)

    resp = client.get("/cards")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["claimed"] for c in body] == [True, False]
    for card in body:
        assert "owner_email" not in card


# ── agent endpoints default-exclude unclaimed ───────────────────────

def test_ask_default_excludes_unclaimed(monkeypatch):
    results = [{"handle": "alice", "name": "Alice"}, {"handle": "bob", "name": "Bob"}]
    captured = {}

    def fake_search(q, role, location, skills, industry, availability, experience_min, limit, include_unclaimed):
        captured["include_unclaimed"] = include_unclaimed
        return results

    monkeypatch.setattr(ask_api.search_service, "search_agents", fake_search)
    monkeypatch.setattr(ask_api.cards_service, "claimed_by_handles", lambda handles: {"alice": True, "bob": False})
    monkeypatch.setattr(ask_api.config, "FEATURE_S03_UNCLAIMED_TIERING", True)

    app = FastAPI()
    app.include_router(ask_api.router, prefix="/ask")
    client = TestClient(app)

    resp = client.get("/ask?q=engineer")
    assert captured["include_unclaimed"] is False
    assert [r["claimed"] for r in resp.json()["results"]] == [True, False]

    resp2 = client.get("/ask?q=engineer&include_unclaimed=true")
    assert captured["include_unclaimed"] is True


def test_ask_flag_off_restores_old_behaviour(monkeypatch):
    captured = {}

    def fake_search(q, role, location, skills, industry, availability, experience_min, limit, include_unclaimed):
        captured["include_unclaimed"] = include_unclaimed
        return []

    monkeypatch.setattr(ask_api.search_service, "search_agents", fake_search)
    monkeypatch.setattr(ask_api.cards_service, "claimed_by_handles", lambda handles: {})
    monkeypatch.setattr(ask_api.config, "FEATURE_S03_UNCLAIMED_TIERING", False)

    app = FastAPI()
    app.include_router(ask_api.router, prefix="/ask")
    client = TestClient(app)
    client.get("/ask?q=engineer")
    assert captured["include_unclaimed"] is True


def test_get_agent_hides_unclaimed_and_uses_card_view(monkeypatch):
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")
    client = TestClient(app)

    card = AgentProfileCard.model_validate(_card_json())
    monkeypatch.setattr(agents_api.config, "FEATURE_S03_UNCLAIMED_TIERING", True)
    monkeypatch.setattr(agents_api.config, "FEATURE_S06_CARDVIEW", True)

    monkeypatch.setattr(agents_api.cards_service, "get_card", lambda agent_id: card)
    monkeypatch.setattr(agents_api.cards_service, "card_is_claimed", lambda handle: False)
    assert client.get("/v1/agents/cid1").status_code == 404

    monkeypatch.setattr(agents_api.cards_service, "card_is_claimed", lambda handle: True)
    resp = client.get("/v1/agents/cid1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["claimed"] is True
    assert "owner_email" not in body


def test_get_agent_cardview_even_when_search_flag_off(monkeypatch):
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")
    client = TestClient(app)

    card = AgentProfileCard.model_validate(_card_json())
    monkeypatch.setattr(agents_api.config, "FEATURE_S03_UNCLAIMED_TIERING", True)
    monkeypatch.setattr(agents_api.config, "FEATURE_S06_CARDVIEW", False)
    monkeypatch.setattr(agents_api.cards_service, "get_card", lambda agent_id: card)
    monkeypatch.setattr(agents_api.cards_service, "card_is_claimed", lambda handle: True)

    resp = client.get("/v1/agents/cid1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["claimed"] is True
    assert "facts" in body
    assert body["cite_as"].endswith("/p/alice")
    assert "owner_email" not in body


def test_public_by_handle_falls_back_when_alias_column_missing(monkeypatch):
    monkeypatch.setattr(cards_service.config, "SUPABASE_DB_SCHEMA", "cards")
    good = MagicMock(data=[{"card": _card_json(), "handle": "alice", "owner_email": None}])

    def select(cols):
        q = MagicMock()
        execute = q.eq.return_value.eq.return_value.execute
        if "alias" in cols.split(","):
            execute.side_effect = RuntimeError("column alias does not exist")
        else:
            execute.return_value = good
        return q

    sb = MagicMock()
    sb.table.return_value.select.side_effect = select
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    card = cards_service.get_card_by_handle_public("alice")
    assert card is not None
    assert card["claimed"] is False
    assert "owner_email" not in card


def test_search_cards_falls_back_when_text_search_raises(monkeypatch):
    class Query:
        def __init__(self):
            self.mode = "start"

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def text_search(self, *_a, **_k):
            self.mode = "tsv"
            return self

        def ilike(self, *_a, **_k):
            self.mode = "ilike"
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            if self.mode == "tsv":
                raise RuntimeError("search_tsv missing")
            return MagicMock(data=[{"card": _card_json(), "handle": "alice"}])

    sb = MagicMock()
    sb.table.side_effect = lambda _name: Query()
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    found = cards_service.search_cards("engineer")
    assert [c.handle for c in found] == ["alice"]


def test_request_takedown_notifies_review_channel(monkeypatch):
    sb = MagicMock()
    sb.table("agent_profile_cards").select("id").eq("handle", "alice").eq("status", "published").execute.return_value = MagicMock(
        data=[{"id": "cid1"}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    notified = {}
    monkeypatch.setattr(cards_service, "_notify_takedown", lambda handle, uid, note: notified.update(handle=handle, uid=uid, note=note))

    assert cards_service.request_takedown("alice", "sub-x", "not me") is True
    assert notified == {"handle": "alice", "uid": "sub-x", "note": "not me"}


def test_notify_takedown_posts_to_mattermost(monkeypatch):
    monkeypatch.setattr(cards_service.config, "MATTERMOST_WEBHOOK_URL", "https://mattermost.example/hooks/abc")
    posted = {}
    monkeypatch.setattr(cards_service.httpx, "post", lambda url, json, timeout: posted.update(url=url, json=json))

    cards_service._notify_takedown("alice", "sub-x", "not me")
    assert posted["url"] == "https://mattermost.example/hooks/abc"
    assert "alice" in posted["json"]["text"]
    assert "not me" in posted["json"]["text"]


def test_notify_takedown_skips_without_webhook(monkeypatch):
    monkeypatch.setattr(cards_service.config, "MATTERMOST_WEBHOOK_URL", "")
    called = {}
    monkeypatch.setattr(cards_service.httpx, "post", lambda *a, **k: called.update(called=True))
    cards_service._notify_takedown("alice", None, None)
    assert called == {}


# ── chat prompt honesty (S14) ───────────────────────────────────────

def test_chat_prompt_discloses_assistant_and_never_impersonates():
    prompt = chat_api._build_system_prompt(_card_json())

    assert "AI assistant" in prompt
    assert "Never claim to be a human" in prompt
    assert "reply as" not in prompt.lower() or "first person" not in prompt.lower()
    assert "Never say you are an AI" not in prompt
    assert "never invent" in prompt


def test_chat_refuses_unclaimed_cards(monkeypatch):
    monkeypatch.setattr(config, "CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setattr(config, "CLOUDFLARE_AI_KEY", "key")
    monkeypatch.setattr(chat_api, "get_card_by_handle", lambda handle: MagicMock())
    monkeypatch.setattr(chat_api, "card_is_claimed", lambda handle: False)

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/v1/chat")
    client = TestClient(app)

    resp = client.post("/v1/chat/alice", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 403


# ── S07 alias ───────────────────────────────────────────────────────

def test_set_card_alias_owner_only_and_reserved(monkeypatch):
    sb = MagicMock()
    chain = sb.table("agent_profile_cards")
    chain.select("id").or_("alias.eq.hello,handle.eq.hello").neq("handle", "alice").execute.return_value = MagicMock(data=[])
    chain.select("owner_email,alias").eq("handle", "alice").execute.return_value = MagicMock(
        data=[{"owner_email": "alice@example.com", "alias": None}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr("services.zynd_memory.ping_revalidate", lambda *a, **k: None)

    ok, msg, slug = cards_service.set_card_alias("alice", "Hello", "alice@example.com")
    assert ok is True and slug == "hello"
    sb.table("agent_profile_cards").update.assert_called_once_with({"alias": "hello"})

    ok2, msg2, _ = cards_service.set_card_alias("alice", "alice", "mallory@example.com")
    assert ok2 is False and msg2 == "not the card owner"

    ok3, msg3, _ = cards_service.set_card_alias("alice", "find", "alice@example.com")
    assert ok3 is False and "reserved" in msg3


def test_set_card_alias_allows_own_handle(monkeypatch):
    sb = MagicMock()
    chain = sb.table("agent_profile_cards")
    chain.select("id").or_("alias.eq.alice,handle.eq.alice").neq("handle", "alice").execute.return_value = MagicMock(data=[])
    chain.select("owner_email,alias").eq("handle", "alice").execute.return_value = MagicMock(
        data=[{"owner_email": "alice@example.com", "alias": None}]
    )
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr("services.zynd_memory.ping_revalidate", lambda *a, **k: None)

    ok, msg, slug = cards_service.set_card_alias("alice", "alice", "alice@example.com")
    assert ok is True and slug == "alice"
    sb.table("agent_profile_cards").update.assert_called_once_with({"alias": "alice"})


def test_set_card_alias_schema_gate_before_clash(monkeypatch):
    monkeypatch.setattr(cards_service.config, "SUPABASE_DB_SCHEMA", "public")
    ok, msg, _ = cards_service.set_card_alias("alice", "hello", "alice@example.com")
    assert ok is False and "not available" in msg


def test_claim_candidates_matches_normalised_linkedin(monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(
        cards_service, "list_published_rows",
        lambda **kw: [
            {"card": _card_json("alice", linkedin="https://www.linkedin.com/in/ALICE-Engineer/"), "handle": "alice", "owner_email": None},
            {"card": _card_json("bob", linkedin="https://www.linkedin.com/in/bob/"), "handle": "bob", "owner_email": None},
            {"card": _card_json("carol", linkedin="https://www.linkedin.com/in/alice-engineer/"), "handle": "carol", "owner_email": "carol@example.com"},
        ],
    )

    out = cards_service.claim_candidates_by_linkedin("https://linkedin.com/in/alice-engineer")
    assert [c["handle"] for c in out] == ["alice"]
    assert "owner_email" not in out[0]