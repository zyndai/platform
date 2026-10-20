"""Cards network regression tests. No real database or Persona calls."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services import network


USER = "00000000-0000-0000-0000-000000000001"
PARTNER = "00000000-0000-0000-0000-000000000002"


def database(monkeypatch, **tables):
    sb = MagicMock()
    queries = {}
    for table, data in tables.items():
        query = MagicMock()
        for method in ("select", "eq", "in_", "or_", "order", "limit", "update", "insert", "upsert", "lte", "gt", "is_"):
            getattr(query, method).return_value = query
        query.not_.is_.return_value = query
        query.execute.return_value = SimpleNamespace(data=data)
        queries[table] = query
    sb.table.side_effect = queries.__getitem__
    monkeypatch.setattr(network, "_sb", lambda: sb)
    return sb, queries


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_requester_cannot_decide_their_own_request(monkeypatch, action):
    monkeypatch.setattr(network, "_connection_row", lambda _: {
        "requester_user_id": USER, "recipient_user_id": PARTNER, "status": "pending",
    })
    with pytest.raises(HTTPException) as error:
        network.respond_connection(USER, "connection", action)
    assert error.value.status_code == 403


def test_dm_send_is_one_rpc_and_carries_the_idempotency_key(monkeypatch):
    seen = {}
    monkeypatch.setattr(network, "_rpc_result", lambda name, params: seen.update(name=name, params=params) or {"message": {"id": "m"}})
    assert network.send_message(USER, "connection", "hello", "client-id") == {"message": {"id": "m"}}
    assert seen == {
        "name": "network_send_dm",
        "params": {
            "p_user": USER, "p_connection": "connection",
            "p_client_id": "client-id", "p_content": "hello",
        },
    }


def test_dm_page_is_one_rpc_with_a_cursor(monkeypatch):
    seen = {}
    monkeypatch.setattr(network, "_rpc_result", lambda name, params: seen.update(name=name, params=params) or {"messages": []})
    network.list_messages(USER, "connection", 25, 10, 20)
    assert seen == {
        "name": "network_dm_messages",
        "params": {
            "p_user": USER, "p_connection": "connection",
            "p_before_seq": 10, "p_after_seq": 20, "p_limit": 25,
        },
    }


def test_group_messages_are_one_rpc(monkeypatch):
    seen = {}
    monkeypatch.setattr(network, "_rpc_result", lambda name, params: seen.update(name=name, params=params) or {"messages": []})
    network.list_group_messages(USER, "group", 50)
    assert seen["name"] == "network_group_messages"
    assert seen["params"]["p_group"] == "group"
    assert seen["params"]["p_limit"] == 50


def test_read_mark_is_one_rpc(monkeypatch):
    seen = {}
    monkeypatch.setattr(network, "_rpc_result", lambda name, params: seen.update(name=name, params=params) or {"status": "ok"})
    network.mark_read(USER, "dm", "connection", 7)
    assert seen == {
        "name": "network_mark_read",
        "params": {"p_user": USER, "p_kind": "dm", "p_id": "connection", "p_seq": 7},
    }


def test_rpc_error_becomes_http_exception(monkeypatch):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = {"error": "Connection not found", "status_code": 404}
    monkeypatch.setattr(network, "_sb", lambda: sb)
    with pytest.raises(HTTPException) as error:
        network.send_message(USER, "connection", "hello")
    assert error.value.status_code == 404
    assert error.value.detail == "Connection not found"


def test_inbox_is_one_rpc_for_connections_groups_and_invitations(monkeypatch):
    calls = []
    payload = {
        "connections": [{"id": "connection"}],
        "groups": [{"id": "group"}],
        "invitations": [{"id": "invite"}],
    }
    monkeypatch.setattr(network, "_rpc_result", lambda name, params: calls.append((name, params)) or payload)
    assert network.list_connections(USER) == {"connections": [{"id": "connection"}]}
    assert network.list_groups(USER) == {"groups": [{"id": "group"}]}
    assert network.list_incoming_invitations(USER) == {"invitations": [{"id": "invite"}]}
    assert calls == [
        ("network_inbox", {"p_user": USER}),
        ("network_inbox", {"p_user": USER}),
        ("network_inbox", {"p_user": USER}),
    ]


def test_connection_note_is_returned_to_the_recipient(monkeypatch):
    monkeypatch.setattr(network, "_partner_card", lambda *_: {"name": "Bob"})
    result = network._serialize_connection({
        "id": "connection", "status": "pending", "recipient_user_id": USER,
        "request_message": "Let's discuss Python APIs",
    }, USER)
    assert result["request_message"] == "Let's discuss Python APIs"


def test_group_search_starts_with_connections_not_first_hundred_cards(monkeypatch):
    monkeypatch.setattr(network, "_require_member", lambda *_: {"role": "owner"})
    _, queries = database(
        monkeypatch,
        group_members=[], group_invitations=[],
        connections=[{"requester_user_id": USER, "recipient_user_id": PARTNER}],
        agent_profile_cards=[{"id": "card", "owner_user_id": PARTNER, "handle": "bob", "card": {"identity": {"name": "Bob"}}}],
    )
    result = network.search_invitable(USER, "group", "Bob")
    queries["agent_profile_cards"].in_.assert_called_once_with("owner_user_id", [PARTNER])
    assert result["people"][0]["handle"] == "bob"


def test_group_decision_uses_atomic_database_operation(monkeypatch):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = {"status": "accepted", "group_id": "group"}
    monkeypatch.setattr(network, "_sb", lambda: sb)
    assert network.respond_invitation(USER, "invite", "accept") == {"status": "accepted", "group_id": "group"}
    sb.rpc.assert_called_once_with("network_respond_invitation", {
        "p_user": USER, "p_invitation": "invite", "p_decision": "accept",
    })
    sb.table.assert_not_called()


@pytest.mark.parametrize("detail,status", [("Invitation expired", 409), ("Invitation not found", 404), ("This group is full", 409)])
def test_group_decision_propagates_database_rejection(monkeypatch, detail, status):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = {"error": detail, "status_code": status}
    monkeypatch.setattr(network, "_sb", lambda: sb)
    with pytest.raises(HTTPException) as error:
        network.respond_invitation(USER, "invite", "accept")
    assert error.value.status_code == status
    assert error.value.detail == detail


def test_group_creation_is_atomic_with_owner_membership(monkeypatch):
    monkeypatch.setattr(network, "_card_for_user", lambda _: {})
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = {"group": {"id": "group", "name": "Team"}}
    monkeypatch.setattr(network, "_sb", lambda: sb)
    assert network.create_group(USER, " Team ", None, "private")["group"]["id"] == "group"
    sb.rpc.assert_called_once_with("network_create_group", {
        "p_user": USER, "p_name": "Team", "p_description": None, "p_visibility": "private",
    })


def test_archived_groups_cannot_be_read_or_messaged(monkeypatch):
    monkeypatch.setattr(network, "_group", MagicMock(side_effect=HTTPException(404, "Group not found")))
    monkeypatch.setattr(network, "_member", lambda *_: {"role": "member"})
    with pytest.raises(HTTPException) as error:
        network._require_member("group", USER)
    assert error.value.status_code == 404


def test_incoming_invitations_are_read_only_named_and_hide_archived_groups(monkeypatch):
    monkeypatch.setattr(network, "get_inbox", lambda _: {
        "invitations": [{"id": "live", "group_id": "group", "group": {"id": "group", "name": "API builders"}}],
    })
    result = network.list_incoming_invitations(USER)
    assert result == {"invitations": [{"id": "live", "group_id": "group", "group": {"id": "group", "name": "API builders"}}]}


def test_group_invitation_does_not_add_membership_and_expires_only_stale_pending_rows(monkeypatch):
    monkeypatch.setattr(network, "_require_member", lambda *_: {"role": "owner"})
    monkeypatch.setattr(network, "_group", lambda _: {})
    monkeypatch.setattr(network, "_connected", lambda *_: True)
    monkeypatch.setattr(network, "_member", lambda *_: None)
    sb, queries = database(monkeypatch, group_invitations=[{"id": "invitation"}])
    assert network.invite_to_group(USER, "group", PARTNER, "Join us") == {"invitation": {"id": "invitation"}}
    assert all(call.args[0] == "group_invitations" for call in sb.table.call_args_list)
    queries["group_invitations"].eq.assert_any_call("status", "pending")
    queries["group_invitations"].eq.assert_any_call("invitee_user_id", PARTNER)
    assert queries["group_invitations"].lte.call_args.args[0] == "expires_at"


def test_ordinary_group_members_cannot_invite(monkeypatch):
    monkeypatch.setattr(network, "_require_member", lambda *_: {"role": "member"})
    with pytest.raises(HTTPException) as error:
        network.invite_to_group(USER, "group", PARTNER, None)
    assert error.value.status_code == 403
