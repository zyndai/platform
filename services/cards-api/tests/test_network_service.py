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


# ── contact links are for accepted connections only ───────────────────────────────

def _partner_row(status):
    return {"requester_user_id": USER, "requester_card_id": "c-me", "recipient_user_id": "other",
            "recipient_card_id": "c-them", "status": status}


def _partner_sb(monkeypatch):
    from unittest.mock import MagicMock

    chain = MagicMock()
    for method in ("select", "eq", "limit"):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = MagicMock(data=[{
        "id": "c-them", "handle": "bob",
        "card": {"identity": {"name": "Bob", "headline": "Founder",
                              "links": {"linkedin": "https://linkedin.com/in/bob", "x": "  ", "github": ""}}},
    }])
    sb = MagicMock()
    sb.table.return_value = chain
    monkeypatch.setattr(network, "_sb", lambda: sb)


@pytest.mark.parametrize("status", ["pending", "declined", "blocked", "revoked"])
def test_partner_links_are_withheld_until_the_connection_is_accepted(monkeypatch, status):
    _partner_sb(monkeypatch)
    partner = network._partner_card(_partner_row(status), USER)
    assert partner["handle"] == "bob" and "links" not in partner


def test_partner_links_are_shared_once_accepted_and_blanks_dropped(monkeypatch):
    _partner_sb(monkeypatch)
    partner = network._partner_card(_partner_row("accepted"), USER)
    assert partner["links"] == {"linkedin": "https://linkedin.com/in/bob"}


def test_the_inbox_carries_links_only_for_accepted_partners(monkeypatch):
    from unittest.mock import MagicMock

    chain = MagicMock()
    for method in ("select", "in_"):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = MagicMock(data=[
        {"id": "c-bob", "card": {"identity": {"links": {"linkedin": "https://linkedin.com/in/bob", "x": " "}}}},
        {"id": "c-cy", "card": {"identity": {"links": {"github": "https://github.com/cy"}}}},
    ])
    sb = MagicMock()
    sb.table.return_value = chain
    monkeypatch.setattr(network, "_sb", lambda: sb)
    inbox = [
        {"id": "1", "status": "accepted", "partner": {"card_id": "c-bob", "handle": "bob"}},
        {"id": "2", "status": "pending", "partner": {"card_id": "c-cy", "handle": "cy"}},
        {"id": "3", "status": "accepted", "partner": {"card_id": "c-gone", "handle": "gone"}},
    ]
    out = network._with_accepted_links(inbox)
    assert out[0]["partner"]["links"] == {"linkedin": "https://linkedin.com/in/bob"}
    assert "links" not in out[1]["partner"]          # pending: nothing shared
    assert "links" not in out[2]["partner"]          # card not found: nothing invented
    chain.in_.assert_called_once_with("id", ["c-bob", "c-gone"])   # one lookup, accepted partners only
    assert network._with_accepted_links([{"status": "pending", "partner": {"card_id": "x"}}])[0]["partner"] == {"card_id": "x"}


# ── people suggestions and connection status ──────────────────────────────────────

CY = "00000000-0000-0000-0000-000000000003"
DEE = "00000000-0000-0000-0000-000000000004"


def _person(handle, name, owner, headline="", **extra):
    return {
        "id": f"card-{handle}", "handle": handle, "owner_user_id": owner,
        "card": {"identity": {"name": name, "headline": headline, "avatar_url": f"https://img/{handle}.png"}},
        **extra,
    }


@pytest.mark.parametrize("raw,clean", [
    ("alice", "alice"),
    ("  @alice  ", "alice"),
    ("@@alice", "alice"),
    ("al,ice", "al ice"),
    ("a),owner_user_id.neq.x,(b", "a owner_user_id.neq.x b"),
    ('x"y\\z', "x y z"),
    ("100%*", "100"),
    ("handle:eq.1", "handle eq.1"),
    ("two   spaces\tand\nnewline", "two spaces and newline"),
    ("x" * 200, "x" * 64),
])
def test_search_text_cannot_reshape_the_or_filter(raw, clean):
    assert network._search_term(raw) == clean


@pytest.mark.parametrize("raw", ["", " ", "a", "@a", "@ ", "%%", ",,", "(*)", " a "])
def test_short_searches_return_nothing_without_touching_the_database(monkeypatch, raw):
    sb, _ = database(monkeypatch)
    assert network.suggest_people(USER, raw) == {"people": []}
    sb.table.assert_not_called()


def test_suggestions_search_claimed_published_cards_by_handle_or_name(monkeypatch):
    _, queries = database(monkeypatch, agent_profile_cards=[], connections=[])
    network.suggest_people(USER, "  @Ali Ce ")
    cards = queries["agent_profile_cards"]
    cards.eq.assert_called_once_with("status", "published")
    assert [c.args for c in cards.not_.is_.call_args_list] == [("owner_email", "null"), ("owner_user_id", "null")]
    cards.or_.assert_called_once_with('handle.ilike."*Ali Ce*",card->identity->>name.ilike."*Ali Ce*"')
    cards.limit.assert_called_once_with(network.SUGGEST_FETCH)
    assert "owner_email" not in cards.select.call_args.args[0]


def test_injected_filter_syntax_stays_inside_the_quoted_pattern(monkeypatch):
    _, queries = database(monkeypatch, agent_profile_cards=[], connections=[])
    network.suggest_people(USER, 'zz"),owner_user_id.neq.0,(handle.eq."')
    (filters,), _ = queries["agent_profile_cards"].or_.call_args
    assert filters == (
        'handle.ilike."*zz owner_user_id.neq.0 handle.eq.*",'
        'card->identity->>name.ilike."*zz owner_user_id.neq.0 handle.eq.*"'
    )
    # still exactly two conditions: nothing in the typed text added a comma, paren or quote
    assert filters.count(",") == 1 and filters.count("(") == 0 and filters.count('"') == 4


def test_suggestions_rank_handle_prefix_then_name_word_prefix_then_contains(monkeypatch):
    rows = [
        _person("zz-contains", "Maria Palmer", CY),          # "alm" only inside "Palmer"
        _person("almost-there", "Zed", PARTNER),             # handle prefix
        _person("quiet", "Bob Almond", DEE),                 # name word prefix
    ]
    database(monkeypatch, agent_profile_cards=rows, connections=[])
    people = network.suggest_people(USER, "alm")["people"]
    assert [p["handle"] for p in people] == ["almost-there", "quiet", "zz-contains"]


def test_suggestions_exclude_the_caller_and_dedupe_by_owner(monkeypatch):
    rows = [
        _person("me", "Me Myself", USER),
        _person("old-cy", "Cy Old", CY),                      # name-prefix match only
        _person("cy", "Cy", CY),                              # same person, better rank: this one wins, once
        _person("cyrus", "Cyrus", DEE),
    ]
    database(monkeypatch, agent_profile_cards=rows, connections=[])
    people = network.suggest_people(USER, "cy")["people"]
    assert [p["handle"] for p in people] == ["cy", "cyrus"]
    assert USER not in str(people)


def test_suggestions_respect_the_limit(monkeypatch):
    rows = [_person(f"sam{i}", f"Sam {i}", f"00000000-0000-0000-0000-0000000001{i:02d}") for i in range(12)]
    database(monkeypatch, agent_profile_cards=rows, connections=[])
    assert len(network.suggest_people(USER, "sam")["people"]) == 8
    assert len(network.suggest_people(USER, "sam", limit=3)["people"]) == 3


def test_suggestions_carry_the_connection_from_one_query_and_no_contact_details(monkeypatch):
    rows = [
        _person("pat", "Pat One", PARTNER, headline="Founder", owner_email="pat@example.com"),
        _person("pam", "Pam Two", CY, headline="Designer"),
        _person("pax", "Pax Three", DEE),
    ]
    rows[0]["card"]["identity"]["links"] = {"linkedin": "https://linkedin.com/in/pat"}
    connections = [
        {"id": "c1", "status": "accepted", "connection_key": network._connection_key(USER, PARTNER),
         "requester_user_id": USER, "recipient_user_id": PARTNER},
        {"id": "c2", "status": "pending", "connection_key": network._connection_key(USER, CY),
         "requester_user_id": CY, "recipient_user_id": USER},
    ]
    sb, queries = database(monkeypatch, agent_profile_cards=rows, connections=connections)
    people = {p["handle"]: p for p in network.suggest_people(USER, "pa")["people"]}

    assert people["pat"]["connection"] == {"id": "c1", "status": "accepted", "incoming": False}
    assert people["pam"]["connection"] == {"id": "c2", "status": "pending", "incoming": True}
    assert people["pax"]["connection"] is None
    assert people["pat"]["headline"] == "Founder"
    assert set(people["pat"]) == {"card_id", "handle", "name", "headline", "avatar_url", "connection"}
    assert "pat@example.com" not in str(people) and "linkedin" not in str(people)
    # every result's connection comes back in a single query keyed by connection_key
    assert [c.args[0] for c in sb.table.call_args_list].count("connections") == 1
    queries["connections"].in_.assert_called_once()
    assert queries["connections"].in_.call_args.args[0] == "connection_key"
    assert len(queries["connections"].in_.call_args.args[1]) == 3


def test_no_matches_skips_the_connection_lookup(monkeypatch):
    sb, _ = database(monkeypatch, agent_profile_cards=[], connections=[])
    assert network.suggest_people(USER, "nobody") == {"people": []}
    assert [c.args[0] for c in sb.table.call_args_list] == ["agent_profile_cards"]


def _status(monkeypatch, *, owner=PARTNER, connection=None, own_card=True):
    monkeypatch.setattr(network, "_card_for_handle", lambda handle: {"id": "card-bob", "handle": handle, "owner_user_id": owner})
    monkeypatch.setattr(network, "_find_card_for_user", lambda uid: {"id": "card-me"} if own_card else None)
    database(monkeypatch, connections=[connection] if connection else [])
    return network.connection_status(USER, "bob")


def _row(status, requester=USER, recipient=PARTNER):
    return {"id": "conn", "status": status, "connection_key": "k",
            "requester_user_id": requester, "recipient_user_id": recipient}


def test_status_for_your_own_card_is_self(monkeypatch):
    assert _status(monkeypatch, owner=USER) == {"self": True}


def test_status_without_a_connection_can_connect(monkeypatch):
    assert _status(monkeypatch) == {"connection": None, "can_connect": True, "reason": None}


def test_status_reports_but_does_not_raise_when_you_have_no_card(monkeypatch):
    result = _status(monkeypatch, own_card=False)
    assert result["connection"] is None and result["can_connect"] is False
    assert "Card" in result["reason"]


def test_status_for_a_missing_card_is_a_404(monkeypatch):
    monkeypatch.setattr(network, "_card_for_handle", MagicMock(side_effect=HTTPException(404, "That verified Card is not available")))
    with pytest.raises(HTTPException) as error:
        network.connection_status(USER, "ghost")
    assert error.value.status_code == 404


@pytest.mark.parametrize("row,incoming", [
    (_row("pending"), False),
    (_row("pending", requester=PARTNER, recipient=USER), True),
    (_row("accepted"), False),
])
def test_status_open_connections_are_reported_and_not_connectable(monkeypatch, row, incoming):
    result = _status(monkeypatch, connection=row)
    assert result["connection"] == {"id": "conn", "status": row["status"], "incoming": incoming}
    assert result["can_connect"] is False and result["reason"]


@pytest.mark.parametrize("status", ["declined", "revoked", "blocked"])
def test_status_decided_connections_are_final_so_connect_is_not_offered(monkeypatch, status):
    # _create_connection hands back the existing row whatever its status and respond_connection only
    # moves a row out of `pending`, so a new request here could never succeed.
    result = _status(monkeypatch, connection=_row(status))
    assert result["connection"]["status"] == status
    assert result["can_connect"] is False and result["reason"]


def test_a_blocked_status_does_not_say_who_blocked(monkeypatch):
    mine = _status(monkeypatch, connection=_row("blocked"))["reason"]
    theirs = _status(monkeypatch, connection=_row("blocked", requester=PARTNER, recipient=USER))["reason"]
    assert mine == theirs and "block" not in mine.lower()


def test_status_does_not_look_up_your_card_when_a_connection_exists(monkeypatch):
    lookup = MagicMock(return_value=None)
    monkeypatch.setattr(network, "_card_for_handle", lambda handle: {"id": "c", "handle": handle, "owner_user_id": PARTNER})
    monkeypatch.setattr(network, "_find_card_for_user", lookup)
    database(monkeypatch, connections=[_row("accepted")])
    assert network.connection_status(USER, "bob")["connection"]["status"] == "accepted"
    lookup.assert_not_called()
