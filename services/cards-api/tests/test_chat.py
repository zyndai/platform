from api.chat import _build_system_prompt
from models.card import AgentProfileCard
from services.card_view import build_card_view


def test_prompt_discloses_assistant_and_includes_facts():
    card = AgentProfileCard.model_validate({
        "id": "abc",
        "handle": "alice",
        "identity": {"name": "Alice Chen", "headline": "Founder", "links": {}},
        "summary": "Builds agents.",
        "zynd_memory": [{"predicate": "is_building", "object": "SendPilot", "approved_at": "2026-10-08T00:00:00+00:00"}],
    })
    prompt = _build_system_prompt(build_card_view(card, claimed=True))
    assert "AI assistant" in prompt
    assert "Never claim to be them" in prompt
    assert "SendPilot" in prompt
    assert "You are Alice Chen." not in prompt
    assert "Never say you are an AI" not in prompt
