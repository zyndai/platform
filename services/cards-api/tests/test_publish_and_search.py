"""
Publish ownership (owner from token, never the body), refresh ownership,
paged listing, and SQL-backed search candidates. Supabase/embeddings mocked.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api import cards as cards_api
from api import onboard as onboard_api
from api.auth import Principal
from models.card import AgentProfileCard
from services import cards as cards_service
from services import search as search_service


def _card_json(handle="alice") -> dict:
    return AgentProfileCard(
        id="cid1",
        status="draft",
        handle=handle,
        identity={"name": "Alice", "headline": "Engineer", "location": "Pune", "avatar_url": "", "links": {}},
        summary="Engineer.",
    ).model_dump(mode="json")


# ── Publish ──────────────────────────────────────────────────────────

@pytest.fixture
def publish_client(monkeypatch):
    job = MagicMock(card=AgentProfileCard.model_validate(_card_json()), handle_github=None,
                    handle_x=None, scrape_raw=None)
    monkeypatch.setattr(onboard_api, "get_job", lambda job_id: job)

    captured = {}

    def fake_insert(card, gh, x, raw, intent, owner_email, custom_handle, claim_token_hash=None, owner_user_id=None):
        captured.update(owner_email=owner_email, claim_token_hash=claim_token_hash, owner_user_id=owner_user_id)
        return "alice"

    monkeypatch.setattr(onboard_api.cards_service, "insert_card", fake_insert)
    # No existing card for anyone in these tests — the dedup lookups always miss.
    monkeypatch.setattr(onboard_api.cards_service, "get_card_by_owner", lambda email: None)
    monkeypatch.setattr(onboard_api.cards_service, "get_card_by_social_handle", lambda gh, x: None)

    async def no_hooks(*_a, **_k):
        return None

    monkeypatch.setattr(onboard_api.hooks, "run_publish_hooks", no_hooks)
    monkeypatch.setattr(config, "AAFO_ISSUER", "https://aafo.example/auth/v1")
    monkeypatch.setattr(
        onboard_api, "verify_supabase_jwt",
        lambda auth: Principal("alice@example.com", "sub-alice", "https://aafo.example/auth/v1") if auth == "Bearer good" else None,
    )
    app = FastAPI()
    app.include_router(onboard_api.router, prefix="/onboard")
    return TestClient(app), captured


def test_publish_ignores_client_supplied_owner_email(publish_client):
    client, captured = publish_client
    body = {"card": _card_json(), "owner_email": "victim@example.com"}

    resp = client.post("/onboard/j1/publish", json=body)

    assert resp.status_code == 200
    assert captured["owner_email"] is None                 # not the victim
    assert resp.json()["claim_token"]                      # anonymous → claim token
    assert captured["claim_token_hash"] == cards_service.hash_claim_token(resp.json()["claim_token"])


def test_publish_takes_owner_from_the_session(publish_client):
    client, captured = publish_client
    body = {"card": _card_json(), "owner_email": "victim@example.com"}

    resp = client.post("/onboard/j1/publish", json=body, headers={"Authorization": "Bearer good"})

    assert resp.status_code == 200
    assert captured["owner_email"] == "alice@example.com"
    assert captured["claim_token_hash"] is None
    assert "claim_token" not in resp.json()


def test_publish_stamps_owner_user_id_only_for_aafo_sessions(publish_client):
    client, captured = publish_client
    body = {"card": _card_json()}

    client.post("/onboard/j1/publish", json=body, headers={"Authorization": "Bearer good"})

    assert captured["owner_user_id"] == "sub-alice"


def test_publish_refuses_to_recreate_an_existing_owned_card(publish_client, monkeypatch):
    client, captured = publish_client
    monkeypatch.setattr(
        onboard_api.cards_service, "get_card_by_owner",
        lambda email: (AgentProfileCard.model_validate(_card_json()), "alice") if email == "alice@example.com" else None,
    )
    body = {"card": _card_json()}

    resp = client.post("/onboard/j1/publish", json=body, headers={"Authorization": "Bearer good"})

    assert resp.status_code == 200
    assert resp.json() == {"existing": True, "handle": "alice"}
    assert captured == {}  # insert_card never called


def test_anonymous_publish_refuses_to_recreate_a_matching_handle(publish_client, monkeypatch):
    client, captured = publish_client
    onboard_api.get_job("j1").handle_github = "octocat"
    monkeypatch.setattr(
        onboard_api.cards_service, "get_card_by_social_handle",
        lambda gh, x: (AgentProfileCard.model_validate(_card_json()), "octo") if gh == "octocat" else None,
    )
    body = {"card": _card_json()}

    resp = client.post("/onboard/j1/publish", json=body)

    assert resp.status_code == 200
    assert resp.json() == {"existing": True, "handle": "octo"}
    assert captured == {}


# ── Refresh endpoints need a real owner ──────────────────────────────

class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def update(self, *_a):
        return self

    def execute(self):
        return MagicMock(data=self.rows)


@pytest.fixture
def cards_client(monkeypatch):
    rows = _Rows([{"owner_email": None, "card": {}}])
    sb = MagicMock()
    sb.table.return_value = rows
    monkeypatch.setattr(cards_api.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(
        cards_api, "verify_supabase_jwt",
        lambda auth: Principal("mallory@example.com", "sub-mallory", "https://xmfj.example/auth/v1") if auth else None,
    )
    monkeypatch.setattr(cards_api.cards_service, "get_card_by_handle",
                        lambda h: AgentProfileCard.model_validate(_card_json()))
    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")
    return TestClient(app), rows


def test_refresh_memory_refuses_unowned_card(cards_client):
    client, _ = cards_client
    resp = client.post("/cards/by-handle/alice/refresh-memory", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403
    assert "claim" in resp.json()["detail"]


def test_refresh_memory_refuses_other_owner(cards_client):
    client, rows = cards_client
    rows.rows = [{"owner_email": "alice@example.com", "card": {}}]
    resp = client.post("/cards/by-handle/alice/refresh-memory", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403


def test_patch_passes_claim_token_header_through(cards_client, monkeypatch):
    client, _ = cards_client
    seen = {}

    def fake_update(handle, card, email, new_handle=None, claim_token=None, owner_user_id=None):
        seen.update(claim_token=claim_token, email=email, owner_user_id=owner_user_id)
        return True, handle

    monkeypatch.setattr(cards_api.cards_service, "update_card", fake_update)
    resp = client.patch("/cards/by-handle/alice", json=_card_json(),
                        headers={"Authorization": "Bearer x", "X-Claim-Token": "tok"})
    assert resp.status_code == 200
    # cards_client's session issuer isn't aafo, so owner_user_id stays unset.
    assert seen == {"claim_token": "tok", "email": "mallory@example.com", "owner_user_id": None}


# ── Paged listing ────────────────────────────────────────────────────

class _Paged:
    def __init__(self, total):
        self.total = total
        self.ranges = []
        self._range = (0, 0)

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        self.ranges.append((start, end))
        return self

    def execute(self):
        start, end = self._range
        return MagicMock(data=[{"id": i} for i in range(start, min(end + 1, self.total))])


def test_list_published_rows_reads_past_the_first_page(monkeypatch):
    q = _Paged(total=2500)
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    rows = cards_service.list_published_rows()

    assert len(rows) == 2500
    assert q.ranges == [(0, 999), (1000, 1999), (2000, 2999)]


def test_list_published_rows_respects_limit(monkeypatch):
    q = _Paged(total=2500)
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    assert len(cards_service.list_published_rows(limit=1500)) == 1500


# ── Search candidates ────────────────────────────────────────────────

def test_search_uses_sql_candidates(monkeypatch):
    calls = []

    def rpc(name, params):
        calls.append(name)
        data = {
            "match_cards": [{"id": "cid1", "handle": "alice", "card": _card_json(), "similarity": 0.9}],
            "search_cards_fts": [{"id": "cid1", "handle": "alice", "card": _card_json(), "rank": 0.5}],
        }[name]
        return MagicMock(execute=lambda: MagicMock(data=data))

    sb = MagicMock()
    sb.rpc.side_effect = rpc
    monkeypatch.setattr(search_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(search_service, "embed_text", lambda q: [0.1, 0.2])
    monkeypatch.setattr(search_service.cards_service, "list_published_rows",
                        lambda **kw: pytest.fail("should not full-scan when the RPCs work"))

    results = search_service.search_agents(q="engineer")

    assert calls == ["match_cards", "search_cards_fts"]
    assert [r["handle"] for r in results] == ["alice"]
    assert "Strong overall match for your query" in results[0]["match_reasons"]


def test_search_falls_back_to_scan_when_rpcs_missing(monkeypatch):
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("function match_cards does not exist")
    monkeypatch.setattr(search_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(search_service, "embed_text", lambda q: [])
    monkeypatch.setattr(search_service.cards_service, "list_published_rows",
                        lambda **kw: [{"card": _card_json(), "handle": "alice"}])

    results = search_service.search_agents(q="engineer")

    assert [r["handle"] for r in results] == ["alice"]


# ── Maintenance read-only switch ────────────────────────────────────

def test_maintenance_mode_blocks_writes_but_not_reads(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module.config, "MAINTENANCE_READONLY", True)
    app = FastAPI()
    app.middleware("http")(main_module.maintenance_readonly)

    @app.get("/x")
    async def get_x():
        return {"ok": True}

    @app.post("/x")
    async def post_x():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/x").status_code == 200
    resp = client.post("/x")
    assert resp.status_code == 503
    assert "read-only" in resp.json()["detail"]


def test_maintenance_mode_off_by_default_allows_writes(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module.config, "MAINTENANCE_READONLY", False)
    app = FastAPI()
    app.middleware("http")(main_module.maintenance_readonly)

    @app.post("/x")
    async def post_x():
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/x").status_code == 200


def test_maintenance_503_carries_cors_headers():
    """The real app wraps the maintenance switch in CORS, so a browser sees the
    503 message rather than a CORS failure."""
    import main as main_module

    old = main_module.config.MAINTENANCE_READONLY
    main_module.config.MAINTENANCE_READONLY = True
    try:
        client = TestClient(main_module.app)
        origin = main_module.config.FRONTEND_URL
        resp = client.post("/cards/anything/refresh-memory", headers={"Origin": origin})
        assert resp.status_code == 503
        assert resp.headers.get("access-control-allow-origin") == origin
    finally:
        main_module.config.MAINTENANCE_READONLY = old

