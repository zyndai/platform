"""The public suggested-people route and the outside (LinkedIn) step of suggestions. Who is
suggested is tested in test_suggestions.py."""
import pytest

from models.card import AgentProfileCard
from services import suggested_people as people_service
from services import suggestions


@pytest.fixture(autouse=True)
def _disable_outside_search(monkeypatch):
    # External people come from Memory's service endpoint; off unless a test turns it on.
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "")
    monkeypatch.setattr(people_service, "_zynd_linkedin", (0.0, set()))


def _card(handle, **fields):
    return AgentProfileCard(
        id=handle,
        status="published",
        handle=handle,
        identity={"name": handle.title(), "headline": "Engineer", "avatar_url": "avatar"},
        **fields,
    )


def _app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import cards as cards_api

    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")
    return TestClient(app)


def test_public_endpoint_returns_404_for_missing_card(monkeypatch):
    monkeypatch.setattr(suggestions, "owner_row", lambda _h: None)
    assert _app().get("/cards/by-handle/missing/suggested-people").status_code == 404


def test_public_endpoint_returns_the_owners_suggestions(monkeypatch):
    seen = {}

    def for_owner_row(row, surface, k):
        seen.update(surface=surface, k=k)
        return {"handle": "jane", "people": [{"handle": "alex"}], "outside": []}

    monkeypatch.setattr(suggestions, "owner_row", lambda _h: {"id": "c-jane", "handle": "jane"})
    monkeypatch.setattr(suggestions, "for_owner_row", for_owner_row)
    response = _app().get("/cards/by-handle/jane/suggested-people")
    assert response.status_code == 200
    assert response.json() == {"handle": "jane", "people": [{"handle": "alex"}], "outside": []}
    assert seen == {"surface": "api", "k": 2}          # no digest cooldown, nothing recorded


# ── outside requests ─────────────────────────────────────────────────────────────────────

def test_one_outside_request_per_kind_of_person_wanted_near_the_owner():
    card = _card("jane", connect_with=["Founders", "Investors"],
                 working_on=["Building with AI", "Open source"], love_talking_about=["Agentic AI"])
    card.identity.location = "Pune, India"
    assert people_service.outside_search_requests(card) == [
        {"titles": ["Founder"], "keywords": ["AI", "open source"], "location": "Pune, India", "limit": 4},
        {"titles": ["Investor"], "keywords": ["AI", "open source"], "location": "Pune, India", "limit": 4},
    ]


def test_outside_request_by_keywords_when_nobody_is_named():
    card = _card("jane", working_on=["Building with AI"])
    assert people_service.outside_search_requests(card) == [
        {"titles": [], "keywords": ["AI"], "location": "", "limit": 4}]    # not India-only: no country assumed


def test_no_outside_request_without_anything_to_search_with():
    assert people_service.outside_search_requests(_card("jane")) == []


def _memory_reply(monkeypatch, payload=None, status=200, exc=None):
    sent = []

    class Resp:
        status_code = status
        text = "boom"

        def json(self):
            return payload

    def fake_post(url, json, headers, timeout):
        sent.append((url, json, headers))
        if exc:
            raise exc
        return Resp()

    monkeypatch.setattr(people_service.httpx, "post", fake_post)
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "svc-token")
    monkeypatch.setattr(people_service.config, "MEMORY_LAYER_URL", "https://memory.example/")
    return sent


PEOPLE = [
    {"name": "Pat", "title": "Founder", "company": "Acme", "linkedin_url": "https://linkedin.com/in/pat",
     "has_email": True, "connection_eligible": False, "source": "quickenrich"},
    {"name": "Sam", "title": "Founder", "company": "Beta", "linkedin_url": "https://linkedin.com/in/sam"},
    {"name": "Lee", "title": "Founder", "company": "Gamma", "linkedin_url": "https://linkedin.com/in/lee"},
]


def test_outside_search_keeps_two_new_people_per_request(monkeypatch):
    card = _card("jane", connect_with=["Founders", "Investors"])
    sent = _memory_reply(monkeypatch, {"people": PEOPLE, "warning": None})
    people = people_service.search_outside(card, {"linkedin.com/in/pat"})
    # Founders: Sam and Lee (Pat is taken); Investors: the same three, all seen by now.
    assert [p["name"] for p in people] == ["Sam", "Lee"]
    assert people[0] == {"name": "Sam", "title": "Founder", "company": "Beta",
                         "linkedin_url": "https://linkedin.com/in/sam", "source": "quickenrich"}
    url, body, headers = sent[0]
    assert url == "https://memory.example/v1/service/outside-people"
    assert headers["Authorization"] == "Bearer svc-token"
    assert body["titles"] == ["Founder"]


def test_outside_search_keeps_where_memory_says_they_are_and_why(monkeypatch):
    ranked = [{"name": "Pat", "title": "Venture Partner", "company": "Seed Fund", "location": "Pune, India",
               "linkedin_url": "https://linkedin.com/in/pat", "score": 0.4, "match_quality": "close",
               "why": ["Investor (title)", " ", 7, "Pune, India", "a", "b"]}]
    _memory_reply(monkeypatch, {"people": ranked, "warning": None})
    (pat,) = people_service.search_outside(_card("jane", connect_with=["Investors"]), set())
    assert pat["location"] == "Pune, India"
    assert pat["why"] == ["Investor (title)", "Pune, India", "a"]       # strings only, at most three
    assert "score" not in pat and "match_quality" not in pat            # nothing else of memory's leaks through


def test_outside_search_stops_asking_once_it_has_enough(monkeypatch):
    card = _card("jane", connect_with=["Founders", "Investors"])
    sent = _memory_reply(monkeypatch, {"people": PEOPLE, "warning": None})
    assert len(people_service.search_outside(card, set(), limit=2)) == 2
    assert len(sent) == 1                               # each request is a paid lookup


@pytest.mark.parametrize("kwargs", [
    {"status": 503}, {"exc": RuntimeError("down")}, {"payload": {"people": "nope"}}, {"payload": []},
])
def test_outside_search_degrades_to_nothing_when_memory_is_unavailable(monkeypatch, kwargs):
    _memory_reply(monkeypatch, **kwargs)
    assert people_service.search_outside(_card("jane", connect_with=["Founders"]), set()) == []


def test_outside_search_is_off_without_the_service_token(monkeypatch):
    monkeypatch.setattr(people_service.httpx, "post", lambda *a, **k: pytest.fail("must not call memory"))
    assert people_service.search_outside(_card("jane", connect_with=["Founders"]), set()) == []
    assert people_service.outside_for(_card("jane", connect_with=["Founders"]), []) == []


def test_outside_for_skips_people_already_on_zynd_and_caps_at_two(monkeypatch):
    _memory_reply(monkeypatch, {"people": [{"name": "NoUrl", "title": "Founder", "linkedin_url": ""}, *PEOPLE]})
    monkeypatch.setattr(people_service, "_zynd_linkedin_keys", lambda: {"linkedin.com/in/pat"})
    from services import invites
    monkeypatch.setattr(invites, "enabled", lambda: True)
    owner = _card("jane", connect_with=["Founders"])
    people = people_service.outside_for(owner, [])
    assert [p["name"] for p in people] == ["NoUrl", "Sam"]
    assert all(p["label"] == "Not on Zynd yet" for p in people)
    assert [p["invitable"] for p in people] == [False, True]      # an invite needs their LinkedIn


def test_zynd_linkedin_profiles_are_read_once_per_ttl(monkeypatch):
    monkeypatch.setattr(people_service, "_zynd_linkedin", (float("-inf"), set()))     # whatever an earlier test cached
    calls = []

    def rows(**kw):
        calls.append(kw)
        return [{"card": {"identity": {"links": {"linkedin": "https://www.linkedin.com/in/alex/"}}}}]

    monkeypatch.setattr("services.cards.list_published_rows", rows)
    assert people_service._zynd_linkedin_keys() == {"linkedin.com/in/alex"}
    assert people_service._zynd_linkedin_keys() == {"linkedin.com/in/alex"}
    assert len(calls) == 1


def test_the_first_read_happens_even_when_the_machine_has_only_just_booted(monkeypatch):
    """time.monotonic() counts from boot, so on a server up for a few minutes an unread cache that started
    at 0.0 looked fresh and the LinkedIn profiles already on Zynd were never read. Starts from the module's
    own initial state (a reload), not from one the test sets up."""
    import importlib
    import time

    fresh = importlib.reload(people_service)
    monkeypatch.setattr(time, "monotonic", lambda: 5.0)
    monkeypatch.setattr("services.cards.list_published_rows", lambda **kw: [
        {"card": {"identity": {"links": {"linkedin": "https://www.linkedin.com/in/alex/"}}}}])
    assert fresh._zynd_linkedin_keys() == {"linkedin.com/in/alex"}
