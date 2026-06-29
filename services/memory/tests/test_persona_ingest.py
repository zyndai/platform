"""Unit tests for persona-profile → memory seeding text assembly (pure, no DB/network)."""
from app.services.persona_ingest import _as_list, _profile_text


def test_full_profile_becomes_first_person_sentences():
    status = {
        "deployed": True, "agent_id": "zns:abc",
        "description": "Building an AI memory layer",
        "capabilities": ["Python", "distributed systems"],
        "profile": {"title": "Founder", "organization": "ZYND",
                    "location": "San Francisco", "interests": ["agents", "search"]},
    }
    text = _profile_text(status)
    assert text == (
        "Building an AI memory layer. "
        "I work as Founder at ZYND. "
        "I am based in San Francisco. "
        "I have expertise in Python, distributed systems. "
        "I am interested in agents, search."
    )


def test_deterministic_for_identical_profile():
    status = {"description": "x" * 20, "profile": {"location": "Berlin"}}
    assert _profile_text(status) == _profile_text(dict(status))  # stable → dedupes downstream


def test_title_or_org_alone():
    assert "My role is Engineer." in _profile_text({"profile": {"title": "Engineer"}})
    assert "I work at Acme." in _profile_text({"profile": {"organization": "Acme"}})


def test_sparse_profile_is_empty():
    assert _profile_text({"deployed": True, "agent_id": "zns:1", "profile": {}}) == ""


def test_interests_accepts_list_or_comma_string():
    assert _as_list(["a", " b ", ""]) == ["a", "b"]
    assert _as_list("a, b ,c") == ["a", "b", "c"]
    assert _as_list(None) == []
