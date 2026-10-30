"""Warm intros never send during drafting and reuse the connection approval boundary."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import config
from api.network import router
from services import network, warm_intros as warm

UID = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
AUTH = {"Authorization": "Bearer test-memory", "X-Zynd-User": UID}


def row(uid, handle, name, **fields):
    return {"id": "card-" + handle, "handle": handle, "owner_user_id": uid,
            "owner_email": handle + "@example.com", "status": "published",
            "card": {"id": "card-" + handle, "handle": handle,
                     "identity": {"name": name, "headline": fields.pop("headline", "Engineer")}, **fields}}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "test-memory")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    me = row(UID, "alice", "Alice", can_help_with=["go-to-market"], connect_with=["Founders"],
             working_on=["AI developer tools"])
    other = row(OTHER, "sarah", "Sarah", headline="Founder", working_on=["AI startup"],
                zynd_memory=[{"predicate": "is_seeking", "object": "go-to-market help"}])
    monkeypatch.setattr(network, "_card_for_user", lambda uid: me)
    monkeypatch.setattr(network, "_card_for_handle", lambda handle: other)
    state = {"connection": None, "can_connect": True}
    monkeypatch.setattr(network, "connection_status", lambda uid, handle: state)
    excluded = {UID: set(), OTHER: set()}
    monkeypatch.setattr(warm.suggestions, "exclusions", lambda r: {
        "card_ids": excluded[r["owner_user_id"]], "handles": set(), "less_like": []})
    send = MagicMock(return_value={"connection": {"id": "c1", "status": "pending", "incoming": False}, "existing": False})
    monkeypatch.setattr(network, "request_connection", send)
    app = FastAPI()
    app.include_router(router, prefix="/cards")
    return SimpleNamespace(client=TestClient(app), me=me, other=other, state=state,
                           excluded=excluded, send=send)


def test_draft_explains_complementary_needs_and_never_creates_a_connection(world):
    response = world.client.post("/cards/network/warm-intros/draft", json={"target_handle": "sarah"}, headers=AUTH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    draft = response.json()
    assert "go-to-market" in draft["message"]
    assert "Your profile says you are looking" in draft["message"]
    assert "go-to-market" in draft["reasons"][0]
    assert "owner_email" not in response.text and "@example.com" not in response.text
    assert "Would you be open to connecting" in draft["message"]
    world.send.assert_not_called()


def test_send_passes_only_the_explicitly_edited_message_to_connection_flow(world):
    response = world.client.post("/cards/network/warm-intros", json={
        "target_handle": "sarah", "message": "  Sarah, can we talk about your AI startup?  "}, headers=AUTH)
    assert response.status_code == 200 and response.json()["connection"]["status"] == "pending"
    world.send.assert_called_once_with(UID, "sarah", "Sarah, can we talk about your AI startup?")


@pytest.mark.parametrize("path", ["/warm-intros/draft", "/warm-intros"])
def test_authentication_precedes_profile_reads_or_sends(world, monkeypatch, path):
    load = MagicMock()
    monkeypatch.setattr(network, "_card_for_user", load)
    response = world.client.post("/cards/network" + path, json={"target_handle": "sarah", **({"message": "hello"} if path == "/warm-intros" else {})})
    assert response.status_code == 403
    load.assert_not_called()
    world.send.assert_not_called()


@pytest.mark.parametrize("uid", [UID, OTHER])
def test_either_person_hiding_or_dismissing_the_other_prevents_new_intros(world, uid):
    world.excluded[uid].add(world.other["id"] if uid == UID else world.me["id"])
    for path in ("/warm-intros/draft", "/warm-intros"):
        body = {"target_handle": "sarah", **({"message": "Hello"} if path == "/warm-intros" else {})}
        assert world.client.post("/cards/network" + path, json=body, headers=AUTH).status_code == 409
    world.send.assert_not_called()


@pytest.mark.parametrize("status", ["blocked", "declined", "revoked"])
def test_a_stale_draft_cannot_revive_a_closed_connection(world, status):
    world.state["connection"] = {"status": status}
    response = world.client.post("/cards/network/warm-intros", json={"target_handle": "sarah", "message": "Hello"}, headers=AUTH)
    assert response.status_code == 409
    world.send.assert_not_called()


@pytest.mark.parametrize("status", ["pending", "accepted"])
def test_retry_delegates_to_existing_pair_deduplication(world, status):
    world.state["connection"] = {"status": status}
    for _ in range(2):
        response = world.client.post("/cards/network/warm-intros", json={"target_handle": "sarah", "message": "Hello"}, headers=AUTH)
        assert response.status_code == 200
    assert world.send.call_count == 2
    # Drafting a second introduction is unnecessary, even if a request arrived meanwhile.
    assert world.client.post("/cards/network/warm-intros/draft", json={"target_handle": "sarah"}, headers=AUTH).status_code == 409


def test_cannot_send_to_yourself_or_override_the_sender(world):
    world.other["owner_user_id"] = UID
    assert world.client.post("/cards/network/warm-intros/draft", json={"target_handle": "alice"}, headers=AUTH).status_code == 422
    assert world.client.post("/cards/network/warm-intros", json={"target_handle": "sarah", "message": "hi", "user_id": OTHER}, headers=AUTH).status_code == 422
    world.send.assert_not_called()


@pytest.mark.parametrize("message", ["", "   ", "x" * 2001])
def test_invalid_message_does_not_send(world, message):
    assert world.client.post("/cards/network/warm-intros", json={"target_handle": "sarah", "message": message}, headers=AUTH).status_code == 422
    world.send.assert_not_called()


def test_expired_needs_are_not_quoted_in_a_draft(world):
    world.other["card"]["zynd_memory"][0]["approved_at"] = "2020-01-01T00:00:00Z"
    result = warm.draft(UID, "sarah")
    assert "go-to-market" not in result["message"]
    assert not any("go-to-market" in reason for reason in result["reasons"])


def test_no_evidence_does_not_fabricate_a_match(world):
    world.me["card"] = {"identity": {"name": "Alice"}}
    with pytest.raises(HTTPException) as error:
        warm.draft(UID, "sarah")
    assert error.value.status_code == 409
    world.send.assert_not_called()


def test_real_connection_flow_requires_both_people_and_deduplicates_retries(monkeypatch):
    from tests.fake_supabase import FakeSupabase
    me = row(UID, "alice", "Alice", connect_with=["Founders"])
    other = row(OTHER, "sarah", "Sarah", headline="Founder")
    sb = FakeSupabase(agent_profile_cards=[me, other])
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    draft = warm.draft(UID, "sarah")
    assert not sb.rows("connections") and not sb.rows("dm_threads")
    first = warm.send(UID, "sarah", draft["message"])
    again = warm.send(UID, "sarah", draft["message"])
    assert len(sb.rows("connections")) == 1 and not sb.rows("dm_threads")
    assert first["connection"]["id"] == again["connection"]["id"]
    assert again["existing"] is True
    connection_id = first["connection"]["id"]
    with pytest.raises(HTTPException) as error:
        network.respond_connection(UID, connection_id, "accept")
    assert error.value.status_code == 403
    assert not sb.rows("dm_threads")
    accepted = network.respond_connection(OTHER, connection_id, "accept")
    assert accepted["connection"]["status"] == "accepted"
    assert len(sb.rows("dm_threads")) == 1
    assert warm.send(UID, "sarah", draft["message"])["existing"] is True
    assert len(sb.rows("connections")) == len(sb.rows("dm_threads")) == 1


def test_model_can_only_select_known_evidence_and_receives_no_contacts(world, monkeypatch):
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps({"ids": ["made-up", "0", "0", {"id": "1"}]})))])
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(config, "get_llm_client", lambda: client)
    world.me["card"]["identity"]["links"] = {"email": "private@example.com"}
    result = warm.draft(UID, "sarah")
    assert len(result["reasons"]) == 1 and "go-to-market" in result["message"]
    assert "private@example.com" not in str(client.chat.completions.create.call_args)
    client.chat.completions.create.side_effect = RuntimeError("timeout")
    assert warm.draft(UID, "sarah")["message"]
    world.send.assert_not_called()
