from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent import a2a_router
from agent.a2a import ZyndAuthError
from api import intros, persona, telegram
from api.auth import get_current_user
from api.guards import Caller, thread_participant
from services import callbacks
import config

OWNER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
INTRO = "00000000-0000-0000-0000-000000000003"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S12_INTROS", True)
    monkeypatch.setattr(config, "CARDS_INTRO_SERVICE_TOKEN", "cards-intro-test")
    app = FastAPI()
    app.include_router(intros.router, prefix="/api/intros")
    app.dependency_overrides[get_current_user] = lambda: {"id": OWNER}
    return TestClient(app)


def test_internal_routes_only_accept_dedicated_service_credential(client, monkeypatch):
    operation = MagicMock()
    monkeypatch.setattr(intros.intros, "operation", operation)
    payload = {
        "card_id": "c1",
        "handle": "alice",
        "requester_uid": OTHER,
        "owner_uid": OWNER,
        "why": "Ask about Python APIs",
        "asks": ["meeting"],
        "idempotency_key": INTRO,
    }
    for headers in ({}, {"Authorization": "Bearer generic-memory-service"}):
        assert (
            client.post(
                "/api/intros/internal", json=payload, headers=headers
            ).status_code
            == 401
        )
    operation.assert_not_called()


def test_owner_decision_uses_session_identity(client, monkeypatch):
    operation = MagicMock(return_value={"status": "accepted"})
    monkeypatch.setattr(intros.intros, "operation", operation)
    response = client.post(
        f"/api/intros/{INTRO}/respond",
        json={"action": "accept", "allow_meetings": False},
    )
    assert response.status_code == 200
    assert operation.call_args.args[1]["p_actor"] == OWNER
    assert (
        client.post(
            f"/api/intros/{INTRO}/respond",
            json={"action": "accept", "actor_uid": OTHER},
        ).status_code
        == 422
    )


def test_listing_is_scoped_to_signed_in_owner(client, monkeypatch):
    read = MagicMock(return_value=[])
    monkeypatch.setattr(intros.intros, "list_for", read)
    assert client.get(f"/api/intros?owner_uid={OTHER}").status_code == 200
    read.assert_called_once_with(OWNER, False, 0)


def test_disabled_flag_does_not_call_db(client, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S12_INTROS", False)
    read = MagicMock()
    monkeypatch.setattr(intros.intros, "list_for", read)
    assert client.get("/api/intros").status_code == 404
    read.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"action": "decline", "allow_meetings": True},
        {"action": "propose_time"},
        {
            "action": "accept",
            "start_time": "2030-01-01T10:00:00",
            "end_time": "2030-01-01T10:20:00",
        },
        {
            "action": "accept",
            "start_time": "2000-01-01T10:00:00Z",
            "end_time": "2000-01-01T10:20:00Z",
        },
    ],
)
def test_invalid_permissions_and_times_rejected_before_rpc(client, monkeypatch, body):
    operation = MagicMock()
    monkeypatch.setattr(intros.intros, "operation", operation)
    assert client.post(f"/api/intros/{INTRO}/respond", json=body).status_code == 422
    operation.assert_not_called()


def test_future_proposal_has_explicit_timezone():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    body = intros.Response(
        action="propose_time", start_time=start, end_time=start + timedelta(minutes=20)
    )
    assert body.end_time - body.start_time == timedelta(minutes=20)


@pytest.fixture
def push_client(monkeypatch):
    app = FastAPI()
    app.include_router(a2a_router.router, prefix="/api/persona")
    monkeypatch.setattr(a2a_router, "get_persona_status", lambda _: {"deployed": True})
    callback = {
        "id": "cb",
        "user_id": OWNER,
        "peer_agent_id": "peer",
        "peer_task_id": "task",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    lookup = MagicMock(return_value=callback)
    monkeypatch.setattr(callbacks, "lookup_by_token", lookup)
    record = MagicMock()
    monkeypatch.setattr(callbacks, "record_push_event", record)
    monkeypatch.setattr(a2a_router, "_track_push_task", lambda coro: coro.close())
    monkeypatch.setattr(
        a2a_router, "verify_message", lambda *args, **kwargs: {"entity_id": None}
    )
    return TestClient(app), callback, lookup, record


def push(client, uid=OWNER, headers=None):
    return client.post(
        f"/api/persona/push/{uid}",
        headers=headers or {},
        json={"taskId": "task", "status": {"state": "completed"}},
    )


def test_task_id_is_not_a_callback_credential(push_client):
    client, _, lookup, record = push_client
    assert push(client).status_code == 401
    lookup.assert_not_called()
    record.assert_not_called()


def test_callback_cannot_cross_user_boundaries(push_client):
    client, _, _, record = push_client
    assert (
        push(client, OTHER, {"Authorization": "Bearer callback-test"}).status_code
        == 403
    )
    record.assert_not_called()


def test_invalid_signature_is_rejected_even_with_valid_callback_token(
    push_client, monkeypatch
):
    client, _, _, record = push_client
    reject = MagicMock(side_effect=ZyndAuthError("bad_signature", "invalid"))
    monkeypatch.setattr(a2a_router, "verify_message", reject)
    assert (
        push(client, headers={"Authorization": "Bearer callback-test"}).status_code
        == 401
    )
    record.assert_not_called()


def test_bearer_only_callback_still_works_when_bound_to_user_and_task(push_client):
    client, _, _, record = push_client
    assert (
        push(client, headers={"Authorization": "Bearer callback-test"}).status_code
        == 200
    )
    record.assert_called_once()


def test_signed_peer_must_match_callback_peer(push_client, monkeypatch):
    client, _, _, record = push_client
    monkeypatch.setattr(
        a2a_router, "verify_message", lambda *a, **k: {"entity_id": "another-peer"}
    )
    assert (
        push(client, headers={"Authorization": "Bearer callback-test"}).status_code
        == 403
    )
    record.assert_not_called()


def test_expired_callback_token_cannot_be_reused(push_client):
    client, callback, _, record = push_client
    callback["expires_at"] = "2000-01-01T00:00:00Z"
    assert (
        push(client, headers={"Authorization": "Bearer callback-test"}).status_code
        == 401
    )
    record.assert_not_called()


def test_telegram_missing_secret_refuses_to_process(monkeypatch):
    app = FastAPI()
    app.include_router(telegram.router)
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "")
    process = AsyncMock()
    monkeypatch.setattr(telegram, "process_telegram_message", process)
    response = TestClient(app).post(
        "/webhook", json={"message": {"chat": {"id": 123}, "text": "untrusted"}}
    )
    assert response.status_code == 503
    process.assert_not_called()


def test_requester_cannot_grant_owner_permissions(monkeypatch):
    app = FastAPI()
    app.include_router(persona.router)
    app.dependency_overrides[thread_participant] = lambda: Caller(user_id=OTHER)
    sb = MagicMock()
    q = sb.table.return_value
    q.select.return_value = q
    q.eq.return_value = q
    q.execute.return_value = SimpleNamespace(
        data=[{"permissions": {}, "receiver_id": "owner-agent"}]
    )
    monkeypatch.setattr(persona, "_supabase", lambda: sb)
    monkeypatch.setattr(persona, "_my_side", lambda *a: "initiator")
    response = TestClient(app).patch(
        "/threads/thread/permissions", json={"can_post_on_my_behalf": True}
    )
    assert response.status_code == 403
    q.update.assert_not_called()


def test_revoked_intro_cannot_reach_calendar_booking(monkeypatch):
    from services import meetings

    monkeypatch.setattr(config, "FEATURE_S12_INTROS", True)
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"status": "revoked"}
    ]
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"status": "revoked"}
    ]
    monkeypatch.setattr(meetings, "_supabase", lambda: sb)
    book = MagicMock()
    monkeypatch.setattr(meetings, "_create_event_for", book)
    with pytest.raises(meetings.MeetingError, match="permission"):
        meetings.book_accepted_meeting({"thread_id": "t1"})
    book.assert_not_called()
