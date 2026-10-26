"""People search Phase 2.1: an owner's card read as "who should I meet?" searches."""
from datetime import datetime, timedelta, timezone

from models.card import AgentProfileCard
from services import suggest_targets
from services.suggest_targets import Target, owner_topics, targets_for
from services.two_way import kind_from_text

NOW = datetime.now(timezone.utc)


def card(**fields) -> AgentProfileCard:
    identity = {"name": "Jane", "headline": fields.pop("headline", "Founder"), "location": fields.pop("location", "")}
    return AgentProfileCard(id="c-jane", status="published", handle="jane", identity=identity, **fields)


def seeking(value: str) -> dict:
    return {"predicate": "is_seeking", "object": value, "source": "declared", "approved_at": NOW.isoformat()}


def test_wants_investors_and_works_on_ai_is_one_investor_search_about_ai():
    targets = targets_for(card(connect_with=["Investors"], working_on=["Building with AI"]))
    assert targets == [Target(kind="Investors", role="investor", topics=("AI",), label="Investor · AI")]


def test_approved_seeking_comes_before_connect_with():
    targets = targets_for(card(connect_with=["Designers"], zynd_memory=[seeking("investment")]))
    assert [t.kind for t in targets] == ["Investors", "Designers"]


def test_free_text_wants_are_matched_to_a_kind_or_searched_as_written():
    targets = targets_for(card(connect_with=["angel investors", "people building agent infra"]))
    assert [(t.kind, t.role, t.q) for t in targets] == [
        ("Investors", "investor", ""),
        ("", "", "people building agent infra"),
    ]


def test_long_free_text_is_not_a_search():
    assert targets_for(card(connect_with=["anyone at all who might be interested in what I am doing"])) == []


def test_kinds_without_a_role_search_by_their_words():
    (target,) = targets_for(card(connect_with=["Healthcare builders"]))
    assert target.role == "" and target.q == "healthcare"


def test_kinds_with_no_searchable_shape_are_skipped():
    assert targets_for(card(connect_with=["Customers"])) == []


def test_nobody_named_searches_for_people_who_work_on_the_same_thing():
    (target,) = targets_for(card(working_on=["Building with AI", "climate software"]))
    assert target == Target(kind="", q="AI", topics=("climate software",), label="Works on AI")


def test_nothing_to_search_with_is_no_targets():
    assert targets_for(card()) == []


def test_a_current_beacon_is_searched_first():
    beacon = {"text": "Looking for a Rust contractor", "created_at": NOW - timedelta(hours=1),
              "expires_at": NOW + timedelta(days=6)}
    targets = targets_for(card(connect_with=["Investors"], beacon=beacon))
    assert targets[0].q == "Looking for a Rust contractor" and targets[0].label == "Your beacon"
    assert targets[1].kind == "Investors"


def test_location_is_never_part_of_a_search():
    targets = targets_for(card(connect_with=["Investors"], location="Pune, India"))
    assert all("pune" not in (t.q + " ".join(t.topics)).lower() for t in targets)


def test_at_most_three_targets():
    targets = targets_for(card(connect_with=["Investors", "Founders", "Designers", "Mentors"]))
    assert len(targets) == suggest_targets.MAX_TARGETS


def test_topics_are_known_labels_then_free_text_then_skills():
    c = card(working_on=["Building with AI"], love_talking_about=["Developer tools"],
             skills=[{"name": "Rust"}, {"name": "Go"}])
    assert owner_topics(c) == ["AI", "developer tools", "Rust"]


def test_kind_from_text():
    assert kind_from_text("Seed-stage VCs") == "Investors"
    assert kind_from_text("product managers") == "Product Managers"
    assert kind_from_text("ML researchers") == "ML Researchers"
    assert kind_from_text("researchers") == "Researchers in my field"
    assert kind_from_text("interesting people") is None
