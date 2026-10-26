"""A2 on the Memory side: only people a search returned to this user can be invited."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mcp_http as m
from app.config import settings
from app.services import invite_refs
from app.services import people_results as pr

LI = "https://www.linkedin.com/in/grace-hopper"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret-0123456789-0123456789")


def ref(uid="u1", **kw):
    return invite_refs.sign(uid, linkedin_url=LI, name="Grace Hopper", headline="Admiral at Navy", **kw)


# ── refs ─────────────────────────────────────────────────────────────────────────

def test_a_ref_round_trips_for_the_user_it_was_issued_to():
    assert invite_refs.verify("u1", ref()) == {"linkedin_url": LI, "name": "Grace Hopper", "headline": "Admiral at Navy"}


def test_a_ref_is_useless_to_anyone_else_and_when_altered_or_old():
    good = ref()
    assert invite_refs.verify("someone-else", good) is None
    body, mac = good.rsplit(".", 1)
    assert invite_refs.verify("u1", body + "." + "0" * len(mac)) is None
    assert invite_refs.verify("u1", "A" + body[1:] + "." + mac) is None            # data altered, mac kept
    assert invite_refs.verify("u1", ref(now=time.time() - 25 * 3600)) is None      # a day old
    for junk in ("", "nonsense", ".", "a.b", None):
        assert invite_refs.verify("u1", junk) is None


def test_no_secret_means_nothing_is_invitable(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "")
    assert ref() == "" and invite_refs.verify("u1", "x.y") is None


def test_a_different_secret_invalidates_old_refs(monkeypatch):
    good = ref()
    monkeypatch.setattr(settings, "jwt_secret", "another-secret-0123456789-0123456789")
    assert invite_refs.verify("u1", good) is None


# ── who is offered an invitation ──────────────────────────────────────────────────

def person(**kw):
    base = {"handle": None, "name": "Grace Hopper", "headline": "Admiral", "claimed": False, "linkedin_url": LI,
            "next_action": "view_profile", "sources": ["linkedin"], "why": [], "score": 0.3}
    return {**base, **kw}


def test_only_unclaimed_people_with_a_name_and_a_linkedin_profile_are_offered_an_invitation():
    people = pr.with_invites([
        person(),                                                   # external LinkedIn result
        person(handle="scraped", name="Scraped Card"),              # unclaimed Card that links LinkedIn
        person(handle="ada", claimed=True, next_action="connect"),  # already has a Card: connect
        person(name=""), person(linkedin_url=""),
    ], "u1", enabled=True)
    assert [p["next_action"] for p in people] == ["invite_to_claim", "invite_to_claim", "connect", "view_profile", "view_profile"]
    assert all("invite_ref" in p for p in people[:2]) and all("invite_ref" not in p for p in people[2:])
    assert invite_refs.verify("u1", people[1]["invite_ref"])["name"] == "Scraped Card"


def test_nothing_is_offered_when_the_feature_is_off():
    (p,) = pr.with_invites([person()], "u1", enabled=False)
    assert p["next_action"] == "view_profile" and "invite_ref" not in p


# ── the tool ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "feature_invite_to_claim", True)


async def call(**kw):
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())):
        return await m.invite_to_claim(uid=kw.pop("uid", "u1"), **kw)


async def test_the_tool_is_inert_when_the_feature_is_off(monkeypatch):
    monkeypatch.setattr(settings, "feature_invite_to_claim", False)
    assert (await call(invite_ref=ref()))["ok"] is False


async def test_the_tool_only_accepts_a_ref_it_issued_to_this_user(on):
    with patch("app.tools.cards_network.create_invite", AsyncMock()) as create:
        for bad in ("", "made-up", ref("another-user")):
            result = await call(invite_ref=bad)
            assert result["ok"] is False and "invite_ref" in result["error"]
    create.assert_not_awaited()


async def test_the_tool_publishes_exactly_the_signed_data_and_nothing_the_caller_adds(on):
    sent = {}

    async def fake_create(pool, uid, linkedin_url, name, headline, message="", from_search=None):
        sent.update(uid=uid, linkedin_url=linkedin_url, name=name, headline=headline, message=message)
        return {"ok": True, "claim_url": "https://cards.zynd.ai/p/grace-hopper", "share_text": "…"}

    with patch("app.tools.cards_network.create_invite", fake_create):
        result = await call(invite_ref=ref(), message="  Would love to talk compilers  ")

    assert result["ok"] is True and result["claim_url"].endswith("/p/grace-hopper")
    assert sent == {"uid": "u1", "linkedin_url": LI, "name": "Grace Hopper", "headline": "Admiral at Navy",
                    "message": "Would love to talk compilers"}


def test_the_tool_needs_the_people_scope():
    from app.services.mcp_scopes import tool_visible
    assert tool_visible("invite_to_claim", ["people:message"]) and tool_visible("invite_to_claim", ["user"])
    assert not tool_visible("invite_to_claim", ["memory:write"])


# ── end to end through find_people ────────────────────────────────────────────────

async def test_find_people_hands_out_a_ref_for_a_linkedin_result(on):
    from app.services import people_search
    ext = {"source": "quickenrich", "name": "Grace Hopper", "title": "Admiral", "company": "Navy", "linkedin_url": LI}
    with patch("app.services.people_search.people_discovery.search_cards", AsyncMock(return_value=([], None))), \
         patch("app.services.people_search.people_discovery.search_quickenrich", AsyncMock(return_value=([ext], None))), \
         patch("app.services.people_search.search_by_query", AsyncMock(return_value=[])), \
         patch("app.services.people_search.card_directory.cards_for_users", AsyncMock(return_value={})):
        result = await people_search.find(MagicMock(), "u1", "admiral", limit=5, wanted={"cards", "zynd", "quickenrich"}, explicit=set())

    (grace,) = result["people"]
    assert grace["next_action"] == "invite_to_claim"
    assert invite_refs.verify("u1", grace["invite_ref"]) == {"linkedin_url": LI, "name": "Grace Hopper", "headline": "Admiral at Navy"}
    assert invite_refs.verify("u2", grace["invite_ref"]) is None
