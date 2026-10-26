"""Which find_people search a connection or invite came from (people search plan 3.5)."""
import json

import pytest

from app.services import people_results as pr
from app.services import search_trail

UID = "user-1"
SID = "3f2b8c4e-6a51-4c43-9d1e-0b5a1f7e2d90"


def card(handle, linkedin=""):
    return pr.person_from_card({"handle": handle, "name": handle.title(), "claimed": True, "linkedin_url": linkedin})


async def test_a_person_from_the_last_search_is_found_by_handle_with_rank_and_source(fake_search_trail_redis):
    zynd = pr.person_from_zynd({"similarity": 0.5}, {"handle": "bo", "name": "Bo", "claimed": True}, "u")
    await search_trail.remember(UID, SID, [card("ada"), zynd])
    assert await search_trail.came_from(UID, handle="ada") == {"search_id": SID, "rank": 1, "source": "card"}
    assert await search_trail.came_from(UID, handle="@BO") == {"search_id": SID, "rank": 2, "source": "zynd"}
    assert await search_trail.came_from(UID, handle="nobody") is None


async def test_a_linkedin_person_is_found_by_profile_url_in_any_spelling():
    grace = pr.person_from_external({"name": "Grace", "title": "Partner", "company": "Acme",
                                     "linkedin_url": "https://www.linkedin.com/in/grace/"}, 0)
    await search_trail.remember(UID, SID, [card("ada"), grace])
    assert await search_trail.came_from(UID, linkedin_url="linkedin.com/in/Grace") == {
        "search_id": SID, "rank": 2, "source": "linkedin"}


async def test_a_person_found_by_a_card_and_by_linkedin_is_named_by_the_card():
    both = pr.merge_people([
        card("grace", linkedin="https://linkedin.com/in/grace"),
        pr.person_from_external({"name": "Grace", "linkedin_url": "https://linkedin.com/in/grace"}, 0)])
    await search_trail.remember(UID, SID, both)
    assert (await search_trail.came_from(UID, linkedin_url="https://linkedin.com/in/grace"))["source"] == "card"


async def test_only_the_last_search_of_that_user_counts(fake_search_trail_redis):
    await search_trail.remember(UID, SID, [card("ada")])
    await search_trail.remember(UID, "second", [card("bo")])
    await search_trail.remember("someone-else", "other", [card("ada")])
    assert await search_trail.came_from(UID, handle="ada") is None
    assert (await search_trail.came_from(UID, handle="bo"))["search_id"] == "second"
    assert (await search_trail.came_from("someone-else", handle="ada"))["search_id"] == "other"


async def test_it_keeps_handles_and_ranks_for_a_day_and_nothing_else(fake_search_trail_redis):
    person = card("ada")
    person["why"] = ["a secret reason"]
    await search_trail.remember(UID, SID, [person])
    (key,) = fake_search_trail_redis.data
    assert fake_search_trail_redis.ttls[key] == 24 * 3600
    stored = json.loads(fake_search_trail_redis.data[key])
    assert stored == {"id": SID, "by": {"handle:ada": [1, "card"]}}


async def test_without_redis_nothing_is_remembered_and_nothing_breaks(monkeypatch):
    class Down:
        async def set(self, *a, **k):
            raise ConnectionError("down")

        async def get(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(search_trail, "_client", lambda: Down())
    await search_trail.remember(UID, SID, [card("ada")])
    assert await search_trail.came_from(UID, handle="ada") is None
    assert await search_trail.came_from(UID) is None            # nothing to look up with


# ── the tools that act on a person from the last search ───────────────────────────

async def _tool(name, fake_call, **kw):
    from unittest.mock import AsyncMock, MagicMock, patch

    import app.mcp_http as m
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())), \
            patch("app.tools.cards_network._call", fake_call):
        return await getattr(m, name)(uid=UID, **kw)


class Recorder:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    async def __call__(self, pool, uid, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json")))
        return self.outcomes.pop(0) if self.outcomes else {"ok": True}


async def test_a_connection_request_to_someone_from_the_last_search_names_that_search():
    await search_trail.remember(UID, SID, [card("ada"), card("bo")])
    call = Recorder({"ok": True, "connection": {"id": "c1"}})
    await _tool("request_card_connection", call, target_handle="@Bo", message="hi")
    assert call.calls == [("POST", "/connections", {
        "target_handle": "@Bo", "message": "hi", "from_search": {"search_id": SID, "rank": 2, "source": "card"}})]


async def test_a_connection_to_someone_not_in_the_last_search_names_no_search():
    await search_trail.remember(UID, SID, [card("ada")])
    call = Recorder()
    await _tool("request_card_connection", call, target_handle="stranger")
    assert call.calls == [("POST", "/connections", {"target_handle": "stranger", "message": None})]


async def test_an_older_cards_that_rejects_the_search_field_still_gets_the_request():
    await search_trail.remember(UID, SID, [card("ada")])
    call = Recorder({"ok": False, "status": 422, "error": "extra fields not permitted"}, {"ok": True, "connection": {"id": "c1"}})
    result = await _tool("request_card_connection", call, target_handle="ada")
    assert result["ok"] is True and len(call.calls) == 2
    assert "from_search" in call.calls[0][2] and "from_search" not in call.calls[1][2]


async def test_other_failures_are_not_retried():
    await search_trail.remember(UID, SID, [card("ada")])
    call = Recorder({"ok": False, "status": 429, "error": "too many requests"})
    result = await _tool("request_card_connection", call, target_handle="ada")
    assert result["ok"] is False and len(call.calls) == 1


async def test_an_invitation_to_a_linkedin_person_from_the_last_search_names_that_search(monkeypatch):
    from app.config import settings
    from app.services import invite_refs
    monkeypatch.setattr(settings, "feature_invite_to_claim", True)
    url = "https://www.linkedin.com/in/grace-hopper"
    grace = pr.person_from_external({"name": "Grace Hopper", "title": "Admiral", "company": "Navy", "linkedin_url": url}, 0)
    await search_trail.remember(UID, SID, [card("ada"), grace])
    ref = invite_refs.sign(UID, linkedin_url=url, name="Grace Hopper", headline="Admiral at Navy")
    call = Recorder({"ok": True, "created": True})
    await _tool("invite_to_claim", call, invite_ref=ref)
    (method, path, body), = call.calls
    assert (method, path) == ("POST", "/invites") and body["from_search"] == {"search_id": SID, "rank": 2, "source": "linkedin"}
