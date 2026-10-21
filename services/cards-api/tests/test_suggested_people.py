import pytest

from models.card import AgentProfileCard
from services import suggested_people as people_service


@pytest.fixture(autouse=True)
def _disable_outside_search(monkeypatch):
    # External people come from Memory's service endpoint; off unless a test turns it on.
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "")


def _card(handle, **fields):
    return AgentProfileCard(
        id=handle,
        status="published",
        handle=handle,
        identity={"name": handle.title(), "headline": "Engineer", "avatar_url": "avatar"},
        **fields,
    )


def test_matches_canonical_keywords_by_same_field(monkeypatch):
    requester = _card(
        "jane",
        working_on=["Building with AI"],
        can_help_with=["Code review"],
    )
    candidates = [
        {"handle": "alex", "card": _card("alex", working_on=[" building with ai "]).model_dump()},
        {"handle": "sam", "card": _card("sam", can_help_with=["Code review"]).model_dump()},
        {"handle": "cross-field", "card": _card("cross-field", love_talking_about=["Building with AI"]).model_dump()},
    ]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    result = people_service.get_suggested_people("jane")

    assert [p["handle"] for p in result["people"]] == ["alex", "sam"]
    assert result["people"][0]["matched_fields"] == {"working_on": ["Building with AI"]}
    assert result["people"][1]["matched_fields"] == {"can_help_with": ["Code review"]}


def test_legacy_aliases_map_to_canonical_keywords(monkeypatch):
    requester = _card("jane", working_on=["Building with AI"])
    candidates = [{
        "handle": "alex",
        "card": _card("alex", working_on=["developing AI agents"]).model_dump(),
    }]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    result = people_service.get_suggested_people("jane")

    assert result["people"][0]["matched_fields"] == {"working_on": ["Building with AI"]}


def test_aliases_are_field_aware(monkeypatch):
    requester = _card("jane", working_on=["ai technology"])
    candidates = [{
        "handle": "alex",
        "card": _card("alex", love_talking_about=["AI / ML"]).model_dump(),
    }]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    assert people_service.get_suggested_people("jane")["people"] == []


def test_canonical_label_from_other_field_does_not_count(monkeypatch):
    requester = _card("jane", working_on=["Design"])
    candidates = [{
        "handle": "alex",
        "card": _card("alex", working_on=["Design"]).model_dump(),
    }]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    assert people_service.get_suggested_people("jane")["people"] == []


def test_higher_score_beats_handle_sort(monkeypatch):
    requester = _card("jane", working_on=["Building with AI"], can_help_with=["Code review"])
    candidates = [
        {"handle": "aaa", "card": _card("aaa", working_on=["Building with AI"]).model_dump()},
        {"handle": "zzz", "card": _card("zzz", working_on=["Building with AI"], can_help_with=["Code review"]).model_dump()},
    ]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    result = people_service.get_suggested_people("jane")

    assert result["people"][0]["handle"] == "zzz"
    assert result["people"][0]["match_score"] == 2


def test_malformed_candidate_is_skipped(monkeypatch):
    requester = _card("jane", working_on=["Building with AI"])
    candidates = [
        {"handle": "bad", "card": {"id": "bad", "working_on": [123]}},
        {"handle": "good", "card": _card("good", working_on=["Building with AI"]).model_dump()},
    ]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    assert [p["handle"] for p in people_service.get_suggested_people("jane")["people"]] == ["good"]


def test_dedupes_matches_excludes_self_and_caps_at_two(monkeypatch):
    requester = _card("jane", working_on=["Building with AI", "building with ai"])
    candidates = [
        {"handle": "jane", "card": requester.model_dump()},
        {"handle": "zed", "card": _card("zed", working_on=["Building with AI"]).model_dump()},
        {"handle": "amy", "card": _card("amy", working_on=["Building with AI"]).model_dump()},
        {"handle": "bob", "card": _card("bob", working_on=["Building with AI"]).model_dump()},
    ]
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: candidates)

    result = people_service.get_suggested_people("jane")

    assert [p["handle"] for p in result["people"]] == ["amy", "bob"]
    assert result["people"][0]["match_score"] == 1


def test_no_matches_and_unknown_interest_return_empty(monkeypatch):
    requester = _card("jane", working_on=["unmapped free text"])
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(
        people_service.cards_service,
        "list_published_rows",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("should not scan without recognized interests")),
    )

    assert people_service.get_suggested_people("jane") == {"handle": "jane", "people": [], "outside": []}


def test_missing_card_returns_none(monkeypatch):
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: None)
    assert people_service.get_suggested_people("missing") is None


def test_published_rows_loaded_with_only_card_and_handle(monkeypatch):
    requester = _card("jane", working_on=["Building with AI"])
    seen = {}

    def list_rows(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", list_rows)

    people_service.get_suggested_people("jane")

    assert seen == {"columns": "card,handle"}


def test_public_endpoint_returns_404_for_missing_card(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import cards as cards_api

    monkeypatch.setattr(cards_api.cards_service, "get_card_by_handle", lambda _h: None)
    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")

    response = TestClient(app).get("/cards/by-handle/missing/suggested-people")

    assert response.status_code == 404


def test_public_endpoint_returns_people(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import cards as cards_api

    monkeypatch.setattr(
        people_service.cards_service,
        "get_card_by_handle",
        lambda _h: _card("jane", working_on=["Building with AI"]),
    )
    monkeypatch.setattr(
        people_service.cards_service,
        "list_published_rows",
        lambda **_kw: [{
            "handle": "alex",
            "card": _card("alex", working_on=["Building with AI"]).model_dump(),
        }],
    )
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "")
    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")

    response = TestClient(app).get("/cards/by-handle/jane/suggested-people")

    assert response.status_code == 200
    assert response.json()["people"][0]["handle"] == "alex"
    assert response.json()["outside"] == []


def test_outside_empty_when_quickenrich_not_configured(monkeypatch):
    requester = _card("jane", connect_with=["Founders"])
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: [])
    monkeypatch.setattr(people_service, "search_outside", lambda _card, _rows: (_ for _ in ()).throw(AssertionError("should not search")))
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "")

    result = people_service.get_suggested_people("jane")

    assert result["outside"] == []


def test_outside_drops_zynd_linkedin_and_caps_at_two(monkeypatch):
    requester = _card("jane", connect_with=["Founders"])
    zynd = _card("alex", working_on=["Building with AI"])
    zynd.identity.links = {"linkedin": "https://www.linkedin.com/in/alex"}
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(
        people_service.cards_service,
        "list_published_rows",
        lambda **_kw: [{"handle": "alex", "card": zynd.model_dump()}],
    )
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "k")
    monkeypatch.setattr(
        people_service,
        "search_outside",
        lambda _card, taken: [
            {"name": "Alex", "title": "Founder", "company": "Acme", "linkedin_url": "https://www.linkedin.com/in/alex"},
            {"name": "Pat", "title": "Founder", "company": "Beta", "linkedin_url": "https://linkedin.com/in/pat"},
            {"name": "Sam", "title": "Founder", "company": "Gamma", "linkedin_url": "https://linkedin.com/in/sam"},
            {"name": "NoUrl", "title": "Founder", "company": "Delta", "linkedin_url": ""},
        ],
    )

    result = people_service.get_suggested_people("jane")

    assert [p["linkedin_url"] for p in result["outside"]] == [
        "https://linkedin.com/in/pat",
        "https://linkedin.com/in/sam",
    ]


def test_outside_keeps_people_without_linkedin(monkeypatch):
    requester = _card("jane", connect_with=["Founders"])
    monkeypatch.setattr(people_service.cards_service, "get_card_by_handle", lambda _h: requester)
    monkeypatch.setattr(people_service.cards_service, "list_published_rows", lambda **_kw: [])
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "k")
    monkeypatch.setattr(
        people_service,
        "search_outside",
        lambda _card, taken: [
            {"name": "Pat", "title": "Mentor", "company": "Acme", "linkedin_url": ""},
        ],
    )

    result = people_service.get_suggested_people("jane")

    assert result["outside"][0]["name"] == "Pat"
    assert "email" not in result["outside"][0]
    assert result["outside"][0]["source"] == "quickenrich"


def test_outside_search_requests_send_titles_then_keywords_near_the_owner():
    card = _card(
        "jane",
        connect_with=["Founders", "Engineers", "Investors"],
        working_on=["Building with AI", "Open source", "B2B SaaS"],
        love_talking_about=["Agentic AI"],
    )
    card.identity.location = "Pune, India"
    requests = people_service.outside_search_requests(card)
    assert len(requests) == 2
    assert requests[0] == {"titles": ["Founder", "Investor"], "keywords": [], "location": "Pune, India", "limit": 4}
    assert requests[1] == {"titles": [], "keywords": ["AI", "open source"], "location": "Pune, India", "limit": 4}


def test_outside_search_requests_assume_no_country_when_the_card_has_no_location():
    card = _card("jane", working_on=["Building with AI"], connect_with=[])
    requests = people_service.outside_search_requests(card)
    assert requests == [{"titles": [], "keywords": ["AI"], "location": "", "limit": 4}]   # not India-only any more


def test_outside_search_requests_empty_without_matching_interests():
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


def test_outside_search_asks_memory_and_takes_one_new_person_per_request(monkeypatch):
    card = _card("jane", connect_with=["Founders"], working_on=["Building with AI"])
    sent = _memory_reply(monkeypatch, {"people": [
        {"name": "Pat", "title": "Founder", "company": "Acme", "linkedin_url": "https://linkedin.com/in/pat",
         "has_email": True, "connection_eligible": False, "source": "quickenrich"},
        {"name": "Sam", "title": "Founder", "company": "Beta", "linkedin_url": "https://linkedin.com/in/sam"},
    ], "warning": None})

    people = people_service.search_outside(card, set())

    # Each request contributes its first person not already taken: Pat from the title request,
    # then Sam from the keyword request (Pat was already taken).
    assert [p["name"] for p in people] == ["Pat", "Sam"]
    assert people[0] == {"name": "Pat", "title": "Founder", "company": "Acme",
                         "linkedin_url": "https://linkedin.com/in/pat", "source": "quickenrich"}
    url, body, headers = sent[0]
    assert url == "https://memory.example/v1/service/outside-people"
    assert headers["Authorization"] == "Bearer svc-token"
    assert body["titles"] == ["Founder"]


@pytest.mark.parametrize("kwargs", [
    {"status": 503}, {"exc": RuntimeError("down")}, {"payload": {"people": "nope"}}, {"payload": []},
])
def test_outside_search_degrades_to_nothing_when_memory_is_unavailable(monkeypatch, kwargs):
    card = _card("jane", connect_with=["Founders"])
    _memory_reply(monkeypatch, **kwargs)
    assert people_service.search_outside(card, set()) == []


def test_outside_search_is_off_without_the_service_token(monkeypatch):
    monkeypatch.setattr(people_service.config, "MEMORY_SERVICE_TOKEN", "")
    monkeypatch.setattr(people_service.httpx, "post", lambda *a, **k: pytest.fail("must not call memory"))
    assert people_service.search_outside(_card("jane", connect_with=["Founders"]), set()) == []
