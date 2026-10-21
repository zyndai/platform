from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError

from app.config import settings
from app.models import ExtractedAssertion
from app.services.quality import assess
from app.taxonomy import decay_fn_for
from app.tools import card_intros
from datetime import datetime, timedelta, timezone


def test_historical_achievement_cannot_be_learning():
    fact = ExtractedAssertion(predicate="is_learning", object_name="Founder of Example, a developer community", object_type="skill_domain", confidence=0.9)
    assert (fact.predicate, fact.object_name) == ("is_founder_of", "Example")
    assert decay_fn_for(fact.predicate) == "none"
    learning = ExtractedAssertion(predicate="is_learning", object_name="Rust async runtimes", object_type="skill_technical", confidence=0.9)
    assert learning.predicate == "is_learning"


@pytest.mark.parametrize("value", ["general", " misc ", "Other", "A complete biography. This describes my past work and accomplishments."])
def test_junk_cannot_enter_topic_capture(value):
    assert assess(value, intended_predicate="has_skill", field="skills").drop
    with pytest.raises(ValidationError):
        ExtractedAssertion(predicate="has_expertise_in", object_name=value, object_type="skill_domain", confidence=0.9)


def test_legacy_founder_suggestion_offers_a_durable_category():
    result = assess("Founder of Example, a developer community", intended_predicate="is_learning")
    assert result.suggested_predicate == "is_founder_of"
    assert result.group == "look" and result.public_label == "Founded: Example"


async def test_invalid_retyping_cannot_clear_a_private_suggestion():
    from app.services.findability import approve
    pool = AsyncMock()
    with pytest.raises(ValueError):
        await approve(pool, "owner", "is_building", "A biography. This is a historical statement.", as_predicate="has_expertise_in")
    pool.acquire.assert_not_called()


@pytest.fixture
def intro_bridge(monkeypatch):
    monkeypatch.setattr(settings, "feature_s12_intros", True)
    monkeypatch.setattr(settings, "s12_identity_issuer", "https://identity.test/auth/v1")
    monkeypatch.setattr(settings, "memory_service_token", "test-service-credential")
    pool = AsyncMock()
    pool.fetchval.return_value = "00000000-0000-0000-0000-000000000001"
    return pool


async def test_missing_identity_has_actionable_error(intro_bridge):
    intro_bridge.fetchval.return_value = None
    result = await card_intros.get_owner_intros(intro_bridge, "owner")
    assert result["code"] == "identity_not_linked" and not result["retryable"]


@pytest.mark.parametrize("status,body,code", [(200, {"intros": []}, None), (503, {}, "upstream_unavailable"), (200, {}, "upstream_unavailable"), (403, {}, "service_configuration")])
async def test_intro_empty_and_failure_are_distinct(monkeypatch, intro_bridge, status, body, code):
    def respond(request):
        return httpx.Response(status, json=body)
    transport = httpx.MockTransport(respond)
    client_class = httpx.AsyncClient
    monkeypatch.setattr(card_intros.httpx, "AsyncClient", lambda **kw: client_class(transport=transport, **kw))
    result = await card_intros.get_owner_intros(intro_bridge, "owner")
    if code:
        assert result["ok"] is False and result["code"] == code
    else:
        assert result["ok"] is True and result["data"] == []


def test_public_mcp_cache_cannot_outlive_a_beacon():
    from app.cards_public_mcp import _bounded_ttl
    end = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    assert 0 <= _bounded_ttl({"beacon": {"expires_at": end}}, 60) <= 5
    assert _bounded_ttl({"beacon": {"expires_at": "2020-01-01T00:00:00Z"}}, 60) == 0
