from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import intros
from api import internal
from services import intros as service
import config

OWNER = "00000000-0000-0000-0000-000000000001"
REQUESTER = "00000000-0000-0000-0000-000000000002"
INTRO = "00000000-0000-0000-0000-000000000003"
KEY = "00000000-0000-0000-0000-000000000004"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S12_INTROS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "SUPABASE_URL", "https://shared.test")
    monkeypatch.setattr(config, "AAFO_ISSUER", "https://shared.test/auth/v1")
    monkeypatch.setattr(
        intros,
        "verify_supabase_jwt",
        lambda auth: (
            SimpleNamespace(sub=REQUESTER, iss=config.AAFO_ISSUER) if auth else None
        ),
    )
    app = FastAPI()
    app.include_router(intros.router, prefix="/cards")
    app.include_router(internal.router, prefix="/internal")
    return TestClient(app)


def headers(role="authenticated"):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"role": role, "aud": "authenticated"}, "test-signature", algorithm="HS256"
        )
    }


def body():
    return {
        "why": "Can we talk about Python APIs?",
        "asks": ["meeting", "message"],
        "idempotency_key": KEY,
    }


def test_requires_human_sign_in(client):
    assert client.post("/cards/by-handle/alice/intro", json=body()).status_code == 401
    assert (
        client.post(
            "/cards/by-handle/alice/intro", json=body(), headers=headers("service_role")
        ).status_code
        == 403
    )


def test_legacy_project_cannot_act_for_shared_identity(client, monkeypatch):
    monkeypatch.setattr(
        intros,
        "verify_supabase_jwt",
        lambda _: SimpleNamespace(sub=REQUESTER, iss="https://legacy.test/auth/v1"),
    )
    assert client.get("/cards/mine/intros", headers=headers()).status_code == 403


def test_disabled_feature_never_calls_upstream(client, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S12_INTROS", False)
    upstream = AsyncMock()
    monkeypatch.setattr(service, "persona", upstream)
    assert (
        client.post(
            "/cards/by-handle/alice/intro", json=body(), headers=headers()
        ).status_code
        == 404
    )
    upstream.assert_not_called()


def test_spoofed_requester_fields_are_rejected(client):
    assert (
        client.post(
            "/cards/by-handle/alice/intro",
            json={**body(), "requester_uid": OWNER},
            headers=headers(),
        ).status_code
        == 422
    )


def test_create_derives_both_identities_and_preserves_retry_key(client, monkeypatch):
    monkeypatch.setattr(
        service, "eligibility", AsyncMock(return_value={"available": True})
    )
    monkeypatch.setattr(
        service,
        "card_row",
        lambda _: {"id": "c1", "handle": "alice", "owner_user_id": OWNER},
    )
    memory = AsyncMock()
    monkeypatch.setattr(service, "memory_identity", memory)
    result = {
        "id": INTRO,
        "card_id": "c1",
        "handle": "alice",
        "requester_uid": REQUESTER,
        "owner_uid": OWNER,
        "status": "pending",
        "thread_id": "thread",
        "created_at": "2026-10-13T00:00:00Z",
        "idempotency_key": KEY,
    }
    upstream = AsyncMock(return_value=result)
    monkeypatch.setattr(service, "persona", upstream)
    sync = AsyncMock()
    monkeypatch.setattr(service, "sync", sync)
    for _ in range(2):
        response = client.post(
            "/cards/by-handle/alice/intro", json=body(), headers=headers()
        )
        assert response.status_code == 200
        assert "idempotency_key" not in response.json()
    payload = upstream.await_args.args[2]
    assert payload["requester_uid"] == REQUESTER and payload["owner_uid"] == OWNER
    assert payload["idempotency_key"] == KEY
    memory.assert_awaited_with(REQUESTER)


def test_upstream_failure_never_creates_projection(client, monkeypatch):
    monkeypatch.setattr(
        service,
        "eligibility",
        AsyncMock(side_effect=intros.HTTPException(503, "Persona unavailable")),
    )
    sync = AsyncMock()
    monkeypatch.setattr(service, "sync", sync)
    assert (
        client.post(
            "/cards/by-handle/alice/intro", json=body(), headers=headers()
        ).status_code
        == 503
    )
    sync.assert_not_called()


def test_owner_list_ignores_forged_owner_query(client, monkeypatch):
    upstream = AsyncMock(return_value={"intros": []})
    monkeypatch.setattr(service, "persona", upstream)
    monkeypatch.setattr(service, "sync", AsyncMock())
    assert (
        client.get(
            f"/cards/mine/intros?owner_uid={OWNER}", headers=headers()
        ).status_code
        == 200
    )
    upstream.assert_awaited_once_with("/users/" + REQUESTER)


def test_unclaimed_private_and_unlinked_cards_are_ineligible(monkeypatch):
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "limit"):
        getattr(q, method).return_value = q
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    for row in (
        {
            "id": "c",
            "status": "private",
            "owner_email": "owner@test",
            "owner_user_id": OWNER,
        },
        {"id": "c", "status": "published", "owner_email": None, "owner_user_id": None},
        {
            "id": "c",
            "status": "published",
            "owner_email": "owner@test",
            "owner_user_id": None,
        },
    ):
        q.execute.return_value = SimpleNamespace(data=[row])
        with pytest.raises(intros.HTTPException) as error:
            service.card_row("alice")
        assert error.value.status_code == 404


def test_pending_intros_are_present_in_digest_without_accept_link():
    from services.owner_notifications import render_weekly

    data = {
        "handle": "alice",
        "name": "Alice",
        "activity": {"available": False, "queries": []},
        "inbox_count": 0,
        "completeness": {"score": 75},
        "intro_inbox_count": 2,
    }
    body, html = render_weekly(data, None)
    assert "2 intro requests" in body and "/intros" in html
    assert "/respond" not in html


def test_mcp_read_bridge_checks_credential_and_issuer(client, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "memory-owner-test")
    upstream = AsyncMock(return_value={"intros": []})
    identity = AsyncMock()
    monkeypatch.setattr(service, "persona", upstream)
    monkeypatch.setattr(service, "memory_identity", identity)
    monkeypatch.setattr(service, "sync", AsyncMock())
    body = {"zynd_uid": REQUESTER, "issuer": config.AAFO_ISSUER}
    assert client.post("/internal/owner-intros", json=body).status_code == 401
    credential = {"Authorization": "Bearer memory-owner-test"}
    assert (
        client.post(
            "/internal/owner-intros",
            json={**body, "issuer": "https://legacy.test/auth/v1"},
            headers=credential,
        ).status_code
        == 403
    )
    assert (
        client.post("/internal/owner-intros", json=body, headers=credential).status_code
        == 200
    )
    upstream.assert_awaited_once_with("/users/" + REQUESTER)
    identity.assert_awaited_once_with(REQUESTER)


def test_incorrect_upstream_owner_is_not_exposed_or_projected(client, monkeypatch):
    monkeypatch.setattr(
        service, "persona", AsyncMock(return_value={"intros": [{"owner_uid": OWNER}]})
    )
    sync = AsyncMock()
    monkeypatch.setattr(service, "sync", sync)
    assert client.get("/cards/mine/intros", headers=headers()).status_code == 503
    sync.assert_not_called()
