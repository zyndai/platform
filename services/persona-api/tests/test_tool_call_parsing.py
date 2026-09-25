"""
Tests for the orchestrator's defensive tool-call recovery and think-tag
stripping.

Some OpenAI-compatible models (DeepSeek-v3 over OpenRouter, seen live)
intermittently emit tool calls as plain text in their native template
instead of as structured `tool_calls`. `_parse_text_tool_calls` recovers
those so the call still executes instead of the raw template leaking to
the user. `strip_think_tags` must also drop a dangling unclosed <think>.
"""

from __future__ import annotations

from agent.orchestrator import _parse_text_tool_calls, strip_think_tags


def test_parses_ascii_deepseek_template():
    leak = (
        "<think>reasoning</think>\n"
        "<tool_calls_begin><tool_call_begin>function<tool_sep>search_zynd_network\n"
        "```json\n"
        '{"query":"UTM tracking","top_k":5}\n'
        "```<tool_call_end><tool_calls_end>"
    )
    calls = _parse_text_tool_calls(leak)
    assert calls and len(calls) == 1
    assert calls[0]["name"] == "search_zynd_network"
    assert calls[0]["arguments"] == {"query": "UTM tracking", "top_k": 5}


def test_parses_unicode_glyph_template():
    leak = (
        "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>"
        "function<｜tool▁sep｜>get_zynd_service_card\n"
        '{"entity_id": "zns:svc:abc"}'
        "<｜tool▁call▁end｜><｜tool▁calls▁end｜>"
    )
    calls = _parse_text_tool_calls(leak)
    assert calls and calls[0]["name"] == "get_zynd_service_card"
    assert calls[0]["arguments"] == {"entity_id": "zns:svc:abc"}


def test_parses_nested_json_args():
    leak = (
        "<tool_calls_begin><tool_call_begin>function<tool_sep>call_zynd_service\n"
        '{"entity_id":"zns:svc:x","data":{"metadata":{"lang":"fr"}}}'
        "<tool_call_end><tool_calls_end>"
    )
    calls = _parse_text_tool_calls(leak)
    assert calls and calls[0]["arguments"]["data"]["metadata"]["lang"] == "fr"


def test_parses_multiple_calls():
    leak = (
        "<tool_calls_begin>"
        "<tool_call_begin>function<tool_sep>search_zynd_network\n"
        '{"query":"x"}<tool_call_end>'
        "<tool_call_begin>function<tool_sep>get_persona_profile\n"
        '{"agent_id":"zns:abc"}<tool_call_end>'
        "<tool_calls_end>"
    )
    calls = _parse_text_tool_calls(leak)
    assert calls and len(calls) == 2
    assert [c["name"] for c in calls] == ["search_zynd_network", "get_persona_profile"]


def test_returns_none_for_normal_text():
    assert _parse_text_tool_calls("I found a UTM link builder. It is active.") is None
    assert _parse_text_tool_calls("") is None


def test_skips_unparseable_args():
    leak = (
        "<tool_calls_begin><tool_call_begin>function<tool_sep>search_zynd_network\n"
        "{not valid json}<tool_call_end><tool_calls_end>"
    )
    assert _parse_text_tool_calls(leak) is None


def test_strip_closed_think():
    assert strip_think_tags("<think>reason</think>Hello") == "Hello"


def test_strip_unclosed_think_to_end():
    # Model emitted reasoning but never closed the tag (budget cut-off).
    assert strip_think_tags("<think>still reasoning, no answer yet") == ""
    assert strip_think_tags("Answer. <think>trailing reasoning") == "Answer."


def test_strip_mixed_closed_and_unclosed():
    assert strip_think_tags("<think>a</think>The answer <think>b") == "The answer"
