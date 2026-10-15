"""S14 remainder: abuse filter, rate limit, and owner question history."""
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api import chat as chat_api


def _app(monkeypatch, *, claimed=True):
    monkeypatch.setattr(config, "CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setattr(config, "CLOUDFLARE_AI_KEY", "key")
    monkeypatch.setattr(chat_api, "get_card_by_handle", lambda handle: MagicMock(model_dump=lambda: {"identity": {"name": "Alice"}}))
    monkeypatch.setattr(chat_api, "card_is_claimed", lambda handle: claimed)
    monkeypatch.setattr(chat_api, "memory_context_for_chat", lambda card: ([], None))

    async def _no_stream(system_prompt, messages):
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_api, "_stream_cf", _no_stream)
    chat_api._hits.clear()
    app = FastAPI()
    app.include_router(chat_api.router, prefix="/v1/chat")
    return TestClient(app)


def _post(client, content, ip="1.2.3.4"):
    return client.post(
        "/v1/chat/alice",
        json={"messages": [{"role": "user", "content": content}]},
        headers={"x-forwarded-for": ip},
    )


def test_prompt_excludes_secrets_and_unapproved_facts():
    secret = "owner-secret@example.com"
    token = "sk-live-SHOULD-NOT-LEAK"
    unapproved = "UNAPPROVED-PRIVATE-FACT"
    prompt = chat_api._build_system_prompt(
        {
            "identity": {"name": "Alice Chen", "headline": "Founder"},
            "summary": "Builds agents.",
            "skills": [],
            "projects": [],
            "writing_samples": [],
            "owner_email": secret,
            "api_key": token,
            "zynd_memory": [{"object": unapproved}],
        },
        memory_facts=[{"text": "SendPilot", "type": "is_building"}],
    )
    assert "SendPilot" in prompt
    assert secret not in prompt
    assert token not in prompt
    assert unapproved not in prompt


def test_thirteenth_message_is_rate_limited(monkeypatch):
    client = _app(monkeypatch)
    for _ in range(12):
        assert _post(client, "what do they build", ip="5.5.5.5").status_code == 200
    resp = _post(client, "what do they build", ip="5.5.5.5")
    assert resp.status_code == 429
    assert "slow down" in resp.json()["detail"]


def test_overlong_and_email_messages_are_refused_without_echo(monkeypatch):
    client = _app(monkeypatch)
    long = "a" * 1001
    email = "reach me at visitor@example.com please"
    for content in (long, email):
        resp = _post(client, content, ip="9.9.9.9")
        assert resp.status_code == 400
        body = resp.text
        assert resp.json()["detail"] == "That question can't be sent."
        assert content not in body
        assert "visitor@example.com" not in body


def test_emit_stores_question_and_category(monkeypatch):
    captured = {}

    def fake_emit(event, **kwargs):
        captured["event"] = event
        captured["meta"] = kwargs.get("meta")

    monkeypatch.setattr("services.events.emit", fake_emit)
    client = _app(monkeypatch)
    text = "Can I book a call?"
    assert _post(client, text, ip="8.8.8.8").status_code == 200
    assert captured["event"] == "chat_message"
    assert captured["meta"] == {"chars": len(text), "category": "contact", "question": text,
                                "question_truncated": False, "question_source": "profile_chat"}


def test_rejected_question_is_not_saved(monkeypatch):
    emit = MagicMock()
    monkeypatch.setattr("services.events.emit", emit)
    client = _app(monkeypatch)
    assert _post(client, "Contact me at private@example.com").status_code == 400
    emit.assert_not_called()
