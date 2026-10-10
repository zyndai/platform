from datetime import datetime, timedelta, timezone

from models.card import AgentProfileCard
from services.card_view import build_card_view, is_expired, live_facts
from services.embed import card_search_text


def _card(**kw):
    data = {
        "id": "abc",
        "status": "published",
        "handle": "alice",
        "identity": {"name": "Alice Chen", "headline": "Founder", "location": "SF", "links": {"linkedin": "https://linkedin.com/in/alice"}},
        "summary": "Builds things.",
        "skills": [{"name": "Python", "level": "expert"}],
        "calendly_url": "https://calendly.com/alice",
        **kw,
    }
    return AgentProfileCard.model_validate(data)


def test_live_facts_drop_expired_seeking():
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    facts = [
        {"predicate": "is_seeking", "object": "cofounder", "approved_at": old},
        {"predicate": "is_building", "object": "agents", "approved_at": datetime.now(timezone.utc).isoformat()},
    ]
    live = live_facts(facts)
    assert [f["object"] for f in live] == ["agents"]
    assert is_expired(facts[0]) is True


def test_build_card_view_strips_contact_when_unclaimed():
    view = build_card_view(
        _card(zynd_memory=[{"predicate": "is_building", "object": "SendPilot", "source": "inferred", "approved_at": datetime.now(timezone.utc).isoformat()}]),
        claimed=False,
    )
    assert view["claimed"] is False
    assert view["calendly_url"] is None
    assert view["links"] == {}
    assert view["facts"][0]["text"] == "SendPilot"
    assert view["cite_as"].endswith("/p/alice")


def test_build_card_view_keeps_contact_when_claimed():
    view = build_card_view(_card(), claimed=True)
    assert view["calendly_url"] == "https://calendly.com/alice"
    assert "linkedin" in view["links"]


def test_search_text_includes_approved_memory():
    card = _card(zynd_memory=[{"predicate": "is_building", "object": "SendPilot"}])
    text = card_search_text(card).lower()
    assert "sendpilot" in text
    assert "building" in text
