from datetime import datetime, timedelta, timezone

from api.chat import _build_system_prompt, memory_context_for_chat
from models.card import AgentProfileCard
from services.card_view import build_card_view


def test_system_prompt_includes_memory_facts_when_provided():
    card = AgentProfileCard.model_validate(
        {
            "id": "cid",
            "handle": "alice",
            "identity": {"name": "Alice Chen", "headline": "Founder"},
            "summary": "Builds agents.",
            "zynd_memory": [
                {
                    "predicate": "is_building",
                    "object": "SendPilot LinkedIn outreach",
                    "source": "declared",
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
    )
    view = build_card_view(card, claimed=True)
    prompt = _build_system_prompt(
        card.model_dump(),
        memory_facts=[f.model_dump(mode="json") for f in view.facts],
        fresh_as_of=view.fresh_as_of,
    )
    assert "SendPilot" in prompt
    assert "Approved memory" in prompt


def test_memory_context_for_chat_drops_expired_seeking():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    card = AgentProfileCard.model_validate(
        {
            "id": "cid",
            "handle": "alice",
            "identity": {"name": "Alice Chen", "headline": "Founder"},
            "summary": "Builds agents.",
            "zynd_memory": [
                {
                    "predicate": "is_seeking",
                    "object": "cofounder",
                    "source": "declared",
                    "approved_at": old,
                },
                {
                    "predicate": "is_building",
                    "object": "SendPilot",
                    "source": "declared",
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                },
            ],
        }
    )
    facts, _fresh = memory_context_for_chat(card)
    texts = [f["text"] for f in facts]
    assert "SendPilot" in texts
    assert "cofounder" not in texts


def test_system_prompt_omits_memory_when_not_passed():
    prompt = _build_system_prompt(
        {
            "identity": {"name": "Alice"},
            "summary": "Hi",
            "skills": [],
            "projects": [],
            "writing_samples": [],
        }
    )
    assert "Approved memory" not in prompt
