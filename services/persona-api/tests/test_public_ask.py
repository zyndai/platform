"""
Tests for the public /ask endpoint (backend/api/public_ask.py).

LLM plumbing is stubbed at the module boundary (_llm_parse/_llm_answer/
_openrouter_chat) so no network is touched. Covers: LLM parse path,
heuristic fallback, explicit mode override, rate limit, GET variant,
deterministic answer, and schema exposure.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.public_ask import (
    AskRequest,
    ask_post,
    ask_get,
    _deterministic_answer,
    _heuristic_parse,
    _llm_parse,
    _openrouter_chat,
)


def _fake_request(ip: str = "1.2.3.4") -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


def _run(coro):
    return asyncio.run(coro)


def _results(n=2):
    rows = []
    for i in range(n):
        rows.append({
            "name": f"Person{i}",
            "agent_id": f"a{i}",
            "description": f"Founder building thing{i}. More text.",
            "match_reason": "matched on: x",
        })
    return {"status": "success", "count": n, "total_available": n, "source": "local_db", "results": rows}


# ── Endpoint ──────────────────────────────────────────────────────────


def test_ask_post_llm_parse_and_answer():
    with patch("api.public_ask._llm_parse", return_value=("AI founders", "domain")), \
         patch("api.public_ask.search_zynd_personas", return_value=_results()) as mock_search, \
         patch("api.public_ask._llm_answer", return_value="Here are some founders."):
        result = _run(ask_post(AskRequest(question="find me AI founders"), _fake_request()))

    mock_search.assert_called_once_with("AI founders", 8, "", False, False)
    assert result["answer"] == "Here are some founders."
    assert result["mode"] == "domain"
    assert result["query_used"] == "AI founders"
    assert result["count"] == 2


def test_ask_post_similarity_marker_falls_back_to_heuristic():
    with patch("api.public_ask._llm_parse", return_value=None), \
         patch("api.public_ask.search_similar_people", return_value=_results(1)) as mock_similar, \
         patch("api.public_ask._llm_answer", return_value=None):
        result = _run(ask_post(AskRequest(question="people similar to me, I am an AI founder"), _fake_request()))

    mock_similar.assert_called_once_with("people similar to me, I am an AI founder", 8)
    assert result["mode"] == "similar"
    assert "Found" in result["answer"]  # deterministic fallback answer


def test_ask_post_explicit_mode_skips_llm_parse():
    with patch("api.public_ask._llm_parse", side_effect=AssertionError("parse must be skipped")), \
         patch("api.public_ask.search_similar_people", return_value=_results(1)), \
         patch("api.public_ask._llm_answer", return_value="answer"):
        result = _run(ask_post(AskRequest(question="who is like me", mode="similar"), _fake_request()))
    assert result["mode"] == "similar"


def test_ask_post_empty_question_422():
    with pytest.raises(HTTPException) as exc:
        _run(ask_post(AskRequest(question="   "), _fake_request()))
    assert exc.value.status_code == 422


def test_ask_get_variant():
    with patch("api.public_ask._llm_parse", return_value=("climate founders", "domain")), \
         patch("api.public_ask.search_zynd_personas", return_value=_results(1)) as mock_search, \
         patch("api.public_ask._llm_answer", return_value="found them"):
        result = _run(ask_get(_fake_request(), question="find climate founders", mode=None, limit=3))
    mock_search.assert_called_once_with("climate founders", 3, "", False, False)
    assert result["count"] == 1


def test_ask_rate_limited():
    import api.public_ask as pa

    pa._ASK_HITS.clear()
    old_max = pa._ASK_MAX_PER_WINDOW
    pa._ASK_MAX_PER_WINDOW = 2
    try:
        with patch("api.public_ask._llm_parse", return_value=("x", "domain")), \
             patch("api.public_ask.search_zynd_personas", return_value=_results(0)), \
             patch("api.public_ask._llm_answer", return_value=None):
            req = _fake_request(ip="7.7.7.7")
            _run(ask_post(AskRequest(question="a"), req))
            _run(ask_post(AskRequest(question="b"), req))
            with pytest.raises(HTTPException) as exc:
                _run(ask_post(AskRequest(question="c"), req))
            assert exc.value.status_code == 429
    finally:
        pa._ASK_MAX_PER_WINDOW = old_max
        pa._ASK_HITS.clear()


# ── LLM helpers ───────────────────────────────────────────────────────


def test_openrouter_chat_returns_none_without_config():
    with patch("api.public_ask.config.OPENROUTER_API_KEY", ""), \
         patch("api.public_ask.config.ASK_ENDPOINT_MODEL", ""):
        assert _openrouter_chat([{"role": "user", "content": "hi"}]) is None


def test_llm_parse_decodes_json():
    with patch("api.public_ask._openrouter_chat", return_value='{"query": "AI founders", "mode": "domain"}'):
        assert _llm_parse("find AI founders") == ("AI founders", "domain")


def test_llm_parse_bad_json_returns_none():
    with patch("api.public_ask._openrouter_chat", return_value="not json"):
        assert _llm_parse("find AI founders") is None


def test_llm_parse_call_failure_returns_none():
    with patch("api.public_ask._openrouter_chat", return_value=None):
        assert _llm_parse("find AI founders") is None


def test_heuristic_parse_detects_similarity():
    assert _heuristic_parse("people similar to me, I am a founder")[1] == "similar"
    assert _heuristic_parse("find me AI founders")[1] == "domain"


# ── Deterministic answer ──────────────────────────────────────────────


def test_deterministic_answer_lists_names():
    answer = _deterministic_answer("domain", _results(2)["results"])
    assert "Found 2" in answer
    assert "Person0" in answer and "Person1" in answer


def test_deterministic_answer_empty():
    assert "couldn't find" in _deterministic_answer("domain", []).lower()


# ── Schema ────────────────────────────────────────────────────────────


def test_minimal_schema_includes_ask():
    from api.public_search import _public_schema

    s = _public_schema("https://dev.persona.zynd.ai")
    ask = s["paths"]["/api/public/ask"]
    assert set(ask.keys()) == {"post", "get"}
    assert ask["get"]["parameters"][0]["name"] == "question"
    assert ask["post"]["requestBody"]["required"] is True