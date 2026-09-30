from models.card import AgentProfileCard
from services import suggested_people as people_service


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

    assert people_service.get_suggested_people("jane") == {"handle": "jane", "people": []}


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
    app = FastAPI()
    app.include_router(cards_api.router, prefix="/cards")

    response = TestClient(app).get("/cards/by-handle/jane/suggested-people")

    assert response.status_code == 200
    assert response.json()["people"][0]["handle"] == "alex"
