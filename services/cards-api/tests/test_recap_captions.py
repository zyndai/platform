import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import config
from services import recap_captions

SNAPSHOT = {"label": "October 2026", "in_progress": False, "highlights": [
    {"id": "repo", "kind": "repository", "title": "alice/tool", "url": "https://github.com/alice/tool"},
    {"id": "github", "kind": "github", "title": "GitHub contributions", "count": 34},
]}
FACTS = "I created 1 new public repository (alice/tool) and made 34 GitHub contributions."
FALLBACK = f"Hi connections, in October 2026, {FACTS} Looking forward to sharing what comes next."
OPENING = "Hi connections, here is a quick look at what I have been working on in October 2026."
CLOSING = "If you are building something similar, I would love to connect."


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-only")
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps({"opening": OPENING, "closing": CLOSING})))])
    monkeypatch.setattr(config, "get_llm_client", lambda: client)
    return client


def test_llm_writes_social_framing_while_facts_remain_verbatim(llm):
    assert recap_captions.generate_social_caption(SNAPSHOT, FALLBACK) == {
        "caption": f"{OPENING} {FACTS} {CLOSING}", "source": "llm"}
    llm.with_options.assert_called_once_with(timeout=recap_captions.CAPTION_TIMEOUT_SECONDS, max_retries=0)
    args = llm.chat.completions.create.call_args.kwargs
    assert args["model"] == config.OPENROUTER_MODEL
    assert json.loads(args["messages"][1]["content"]) == {"period": "October 2026", "in_progress": False}
    assert "alice/tool" not in str(args["messages"])
    assert "owner_email" not in str(args["messages"])


@pytest.mark.parametrize("opening,closing", [
    (OPENING.replace("2026", "2027"), CLOSING),
    (OPENING, CLOSING + " Visit https://example.com"),
    ("Bad output", CLOSING),
    (OPENING + " I have not shipped anything yet.", CLOSING),
    (OPENING + " I have no learning milestones yet.", CLOSING),
    (OPENING + " I created 999 repositories.", CLOSING),
])
def test_rejects_new_claims_links_and_wrong_period(llm, opening, closing):
    llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({"opening": opening, "closing": closing})
    assert recap_captions.generate_social_caption(SNAPSHOT, FALLBACK) == {"caption": FALLBACK, "source": "template"}


def test_missing_key_empty_facts_and_provider_failures_keep_a_usable_caption(llm, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    assert recap_captions.generate_social_caption(SNAPSHOT, FALLBACK)["caption"] == FALLBACK
    llm.chat.completions.create.assert_not_called()
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-only")
    assert recap_captions.generate_social_caption({**SNAPSHOT, "highlights": []}, "empty")["caption"] == "empty"
    llm.chat.completions.create.side_effect = TimeoutError()
    assert recap_captions.generate_social_caption(SNAPSHOT, FALLBACK)["source"] == "template"
