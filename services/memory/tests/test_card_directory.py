"""Zynd user -> Card resolution (the bridge between memory's people and the Cards index)."""
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import settings
from app.services import card_directory as cd

SUPA = "11111111-1111-1111-1111-111111111111"
GHOST = "22222222-2222-2222-2222-222222222222"
LINKED = "33333333-3333-3333-3333-333333333333"


class Pool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, query, ids):
        return [r for r in self.rows if str(r["id"]) in ids]


@pytest.fixture
def cards_api(monkeypatch):
    monkeypatch.setattr(settings, "cards_api_url", "http://cards.test")
    monkeypatch.setattr(settings, "memory_service_token", "tok")
    calls = []

    def install(handler):
        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return handler(request)
        transport = httpx.MockTransport(respond)
        real = httpx.AsyncClient
        monkeypatch.setattr(cd.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
        return calls
    return install


async def test_canonical_ids_use_the_supabase_id_else_the_row_id():
    pool = Pool([{"id": LINKED, "supabase_user_id": SUPA}, {"id": GHOST, "supabase_user_id": None}])
    assert await cd.canonical_ids(pool, [LINKED, GHOST, "not-a-uuid"]) == {LINKED: SUPA, GHOST: GHOST}


async def test_cards_for_users_maps_cards_back_to_memory_ids(cards_api):
    calls = cards_api(lambda req: httpx.Response(200, json={"cards": {
        SUPA: {"handle": "ada", "name": "Ada", "headline": "Founder", "location": "Pune", "claimed": True}}}))
    pool = Pool([{"id": LINKED, "supabase_user_id": SUPA}, {"id": GHOST, "supabase_user_id": None}])

    out = await cd.cards_for_users(pool, [LINKED, GHOST])

    assert out == {LINKED: {"handle": "ada", "name": "Ada", "headline": "Founder", "location": "Pune", "claimed": True}}
    (request,) = calls
    assert request.url.path == "/internal/cards-for-users"
    assert request.headers["authorization"] == "Bearer tok"
    assert json.loads(request.content) == {"user_ids": [SUPA, GHOST]}


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(503),
    lambda req: httpx.Response(200, json=["not", "a", "dict"]),
    lambda req: httpx.Response(200, text="<html>"),
])
async def test_an_unreachable_or_garbled_cards_service_is_none_not_an_exception(cards_api, handler):
    cards_api(handler)
    assert await cd.cards_for_users(Pool([{"id": LINKED, "supabase_user_id": SUPA}]), [LINKED]) is None


async def test_not_configured_is_none_and_makes_no_request(monkeypatch):
    monkeypatch.setattr(settings, "memory_service_token", "")
    assert await cd.cards_for_canonical([SUPA]) is None
    assert await cd.cards_for_canonical([]) == {}          # nothing to ask is not an outage
