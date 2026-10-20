"""A2 — invite to claim: a LinkedIn-only person becomes a pre-filled unclaimed Card; the
connection request is delivered when they claim it."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import config
from services import cards as cards_service
from services import invites, network
from tests.fake_supabase import FakeSupabase

INVITER = "00000000-0000-0000-0000-0000000000a1"
OWNER = "00000000-0000-0000-0000-0000000000b2"
URL = "https://www.linkedin.com/in/grace-hopper"


def claimed_card(card_id, handle, user_id, linkedin=""):
    return {"id": card_id, "handle": handle, "status": "published", "owner_user_id": user_id,
            "owner_email": f"{handle}@example.com",
            "card": {"identity": {"name": handle.title(), "headline": "", "links": {"linkedin": linkedin} if linkedin else {}}}}


@pytest.fixture
def world(monkeypatch):
    sb = FakeSupabase(agent_profile_cards=[claimed_card("c-inviter", "ada", INVITER)])
    monkeypatch.setattr(network, "_sb", lambda: sb)
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "FEATURE_A2_INVITE_TO_CLAIM", True)
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://cards.example")
    created = []

    def fake_insert_card(card, gh, x, **kw):
        handle = "grace-hopper"
        sb.new_row("agent_profile_cards", {"id": card.id, "handle": handle, "status": card.status, "owner_user_id": None,
                                           "owner_email": None, "card": card.model_dump(mode="json"),
                                           "created_via": kw.get("created_via")})
        created.append(card)
        return handle

    monkeypatch.setattr(cards_service, "insert_card", fake_insert_card)
    sb.created = created
    return sb


def invite(**kw):
    return invites.create_invite(INVITER, **{"linkedin_url": URL, "name": "Grace Hopper", "headline": "Admiral at Navy", **kw})


# ── creating ──────────────────────────────────────────────────────────────────────

def test_a_linkedin_only_person_becomes_a_prefilled_unclaimed_card(world):
    result = invite(message="Would love to talk compilers")
    (card,) = world.created
    assert card.identity.name == "Grace Hopper" and card.identity.headline == "Admiral at Navy"
    assert card.identity.links == {"linkedin": URL} and card.status == "published"
    assert card.summary == "" and not card.skills       # nothing beyond what LinkedIn showed
    assert world.rows("agent_profile_cards")[-1]["owner_email"] is None and world.rows("agent_profile_cards")[-1]["created_via"] == "invite"
    assert result["created"] is True and result["claim_url"] == "https://cards.example/p/grace-hopper"
    assert result["claim_url"] in result["share_text"]
    (row,) = world.rows("connection_invites")
    assert (row["inviter_user_id"], row["status"], row["message"]) == (INVITER, "pending", "Would love to talk compilers")


def test_inviting_the_same_person_twice_is_idempotent(world):
    first, second = invite(), invite()
    assert len(world.created) == 1 and len(world.rows("connection_invites")) == 1
    assert second["created"] is False and second["invite"]["id"] == first["invite"]["id"]


def test_an_existing_unclaimed_card_is_reused_not_duplicated(world):
    world.new_row("agent_profile_cards", {"id": "c-scraped", "handle": "g-hopper", "status": "published", "owner_user_id": None,
                                          "owner_email": None, "card": {"identity": {"name": "G Hopper", "links": {"linkedin": URL + "/"}}}})
    result = invite()
    assert not world.created and result["claim_url"].endswith("/p/g-hopper")
    assert world.rows("connection_invites")[0]["target_card_id"] == "c-scraped"


def test_someone_who_already_has_a_card_is_pointed_at_it(world):
    world.new_row("agent_profile_cards", claimed_card("c-grace", "grace", OWNER, linkedin=URL))
    with pytest.raises(HTTPException) as err:
        invite()
    assert err.value.status_code == 409 and err.value.detail["handle"] == "grace"
    assert not world.rows("connection_invites")


@pytest.mark.parametrize("bad", ["https://example.com/in/x", "https://linkedin.com/company/acme", "javascript:alert(1)",
                                 "not a url", "https://evil.com/linkedin.com/in/x", "https://linkedin.com/in/"])
def test_only_personal_linkedin_profiles_are_accepted(world, bad):
    with pytest.raises(HTTPException) as err:
        invite(linkedin_url=bad)
    assert err.value.status_code == 422 and not world.created


def test_the_url_is_normalized(world):
    assert invites.clean_linkedin_url("LinkedIn.com/in/Grace-Hopper/") == URL
    assert invites.clean_linkedin_url("http://uk.linkedin.com/in/grace-hopper") == URL


def test_a_name_is_required_and_text_is_trimmed(world):
    with pytest.raises(HTTPException):
        invite(name="   ")
    invite(name="  Grace   Hopper  " + "x" * 300, headline="h" * 500, message="m" * 900)
    assert len(world.created[0].identity.name) <= 120 and len(world.created[0].identity.headline) <= 200
    assert len(world.rows("connection_invites")[0]["message"]) <= 500


def test_you_need_a_claimed_card_to_invite(world, monkeypatch):
    world.tables["agent_profile_cards"].clear()
    with pytest.raises(HTTPException) as err:
        invite()
    assert err.value.status_code == 409


def test_invitations_are_rate_limited_per_day(world):
    for i in range(invites.MAX_INVITES_PER_DAY):
        world.new_row("connection_invites", {"inviter_user_id": INVITER, "inviter_card_id": "c-inviter",
                                             "target_card_id": f"t{i}"})
    with pytest.raises(HTTPException) as err:
        invite()
    assert err.value.status_code == 429


def test_the_feature_is_off_by_default(world, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_A2_INVITE_TO_CLAIM", False)
    for call in (invite, lambda: invites.list_invites(INVITER), lambda: invites.cancel_invite(INVITER, "x")):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 404
    assert invites.deliver_for_card("anything", OWNER) == 0 and invites.deliver_for_user(OWNER) == 0


# ── delivering ────────────────────────────────────────────────────────────────────

def claim(world, handle="grace-hopper", user=OWNER):
    row = next(r for r in world.rows("agent_profile_cards") if r["handle"] == handle)
    row.update(owner_email="grace@example.com", owner_user_id=user)
    return row["id"]


def test_claiming_the_card_delivers_the_invitation_as_a_connection_request(world):
    invite(message="Compilers?")
    card_id = claim(world)

    assert invites.deliver_for_card(card_id, OWNER) == 1

    (connection,) = world.rows("connections")
    assert (connection["requester_user_id"], connection["recipient_user_id"], connection["status"]) == (INVITER, OWNER, "pending")
    assert connection["request_message"] == "Compilers?" and connection["recipient_card_id"] == card_id
    (row,) = world.rows("connection_invites")
    assert row["status"] == "delivered" and row["connection_id"] == connection["id"] and row["delivered_at"]


def test_delivery_happens_once(world):
    invite()
    card_id = claim(world)
    assert invites.deliver_for_card(card_id, OWNER) == 1
    assert invites.deliver_for_card(card_id, OWNER) == 0
    assert len(world.rows("connections")) == 1


def test_existing_connection_between_the_pair_is_reused(world):
    world.new_row("agent_profile_cards", claimed_card("c-grace-old", "grace-old", OWNER))
    invite()
    card_id = claim(world)
    key = ":".join(sorted((INVITER, OWNER)))
    existing = world.new_row("connections", {"connection_key": key, "requester_user_id": OWNER, "requester_card_id": "c-grace-old",
                                             "recipient_user_id": INVITER, "recipient_card_id": "c-inviter", "status": "accepted"})
    invites.deliver_for_card(card_id, OWNER)
    assert len(world.rows("connections")) == 1
    assert world.rows("connection_invites")[0]["connection_id"] == existing["id"]


def test_expired_and_cancelled_invitations_are_not_delivered(world):
    result = invite()
    card_id = claim(world)
    row = world.rows("connection_invites")[0]
    row["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert invites.deliver_for_card(card_id, OWNER) == 0 and row["status"] == "expired"

    row["status"], row["expires_at"] = "pending", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    invites.cancel_invite(INVITER, result["invite"]["id"])
    assert invites.deliver_for_card(card_id, OWNER) == 0 and not world.rows("connections")


def test_nobody_can_invite_themselves_into_a_connection(world):
    invite()
    card_id = claim(world, user=INVITER)            # the inviter claims the card they invited
    assert invites.deliver_for_card(card_id, INVITER) == 0 and not world.rows("connections")


def test_a_broken_inviter_card_does_not_break_the_claim(world):
    invite()
    card_id = claim(world)
    world.tables["agent_profile_cards"][0]["owner_user_id"] = "someone-else"      # inviter no longer owns their card
    assert invites.deliver_for_card(card_id, OWNER) == 0


def test_opening_connections_delivers_invitations_waiting_for_your_card(world, monkeypatch):
    # The inbox is one RPC on the real database; stand in for it with the rows of the fake.
    monkeypatch.setattr(network, "get_inbox", lambda uid: {"connections": [
        network._serialize_connection(r, uid) for r in world.rows("connections")
        if uid in (r["requester_user_id"], r["recipient_user_id"])]})
    invite()
    claim(world)
    listed = network.list_connections(OWNER)
    assert [c["status"] for c in listed["connections"]] == ["pending"] and listed["connections"][0]["incoming"] is True


def test_claiming_via_linkedin_records_the_owner_and_delivers(world, monkeypatch):
    monkeypatch.setattr(config, "AAFO_ISSUER", "https://aafo.example/auth/v1")
    monkeypatch.setattr(config, "WRITES_OWNER_USER_ID", True)
    monkeypatch.setattr(cards_service, "owner_user_metadata_linkedin", lambda p: "grace-hopper")
    invite()
    principal = SimpleNamespace(email="grace@example.com", sub=OWNER, iss=config.AAFO_ISSUER)

    claimed, message = cards_service.claim_card_by_owner("grace-hopper", principal)

    assert claimed, message
    card = next(r for r in world.rows("agent_profile_cards") if r["handle"] == "grace-hopper")
    assert card["owner_user_id"] == OWNER and card["owner_email"] == "grace@example.com"
    assert world.rows("connections")[0]["recipient_user_id"] == OWNER


def test_a_principal_from_another_auth_project_gets_no_owner_user_id(world, monkeypatch):
    monkeypatch.setattr(config, "AAFO_ISSUER", "https://aafo.example/auth/v1")
    monkeypatch.setattr(config, "WRITES_OWNER_USER_ID", True)
    monkeypatch.setattr(cards_service, "owner_user_metadata_linkedin", lambda p: "grace-hopper")
    invite()
    principal = SimpleNamespace(email="grace@example.com", sub=OWNER, iss="https://other-project/auth/v1")
    assert cards_service.claim_card_by_owner("grace-hopper", principal)[0]
    card = next(r for r in world.rows("agent_profile_cards") if r["handle"] == "grace-hopper")
    assert card["owner_user_id"] is None and not world.rows("connections")      # FK would point at a user that is not in aafo


# ── listing / cancelling ──────────────────────────────────────────────────────────

def test_you_see_only_your_own_invitations_and_can_cancel_only_those(world):
    result = invite()
    listed = invites.list_invites(INVITER)["invites"]
    assert [i["target_handle"] for i in listed] == ["grace-hopper"] and "inviter_user_id" not in listed[0]
    assert invites.list_invites(OWNER)["invites"] == []
    with pytest.raises(HTTPException):
        invites.cancel_invite(OWNER, result["invite"]["id"])
    assert invites.cancel_invite(INVITER, result["invite"]["id"])["invite"]["status"] == "cancelled"
    with pytest.raises(HTTPException):
        invites.cancel_invite(INVITER, result["invite"]["id"])          # no longer pending
