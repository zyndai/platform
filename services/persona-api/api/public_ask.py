"""
Public /ask endpoint — plaintext people search for external callers.

POST|GET /api/public/ask  with a natural-language `question`
("find me AI founders in Bangalore", "people similar to me, I'm an AI
startup founder") and get back a natural-language `answer` plus the
structured `results` the search endpoint returns.

Pipeline (all deterministic-fallback-safe):
  1. Optional LLM parse — OpenRouter (OPENROUTER_API_KEY +
     ASK_ENDPOINT_MODEL) maps the question to {query, mode} as JSON.
     When the key/model is unset or the call fails, a keyword heuristic
     takes over (similarity markers → mode="similar", else "domain").
  2. Search — the SAME fast path as /api/public/search/people
     (enrich=False, no webhook resolution).
  3. Answer — LLM-written natural summary of the results; falls back to
     a deterministic formatter when the LLM is unavailable.

Rate-limited per IP (stricter than plain search — LLM calls cost money).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

import config
from api.public_search import _client_ip, _rate_limited
from mcp.tools.zynd_network import search_similar_people, search_zynd_personas

logger = logging.getLogger(__name__)

router = APIRouter()

# Stricter limit than /search/people: each /ask request can spend real
# LLM tokens, so anonymous callers get a tighter per-IP budget.
_ASK_HITS: dict[str, tuple[float, int]] = {}
_ASK_WINDOW_SECONDS = 60.0
_ASK_MAX_PER_WINDOW = 10

DEFAULT_LIMIT = 8

_SIMILAR_MARKERS = (
    "similar to", "like me", "people like", "someone like", "same as",
    "match my", "matches my", "like-minded", "like minded",
)


# ── LLM plumbing (OpenRouter) ────────────────────────────────────────


def _openrouter_chat(messages: list[dict], response_format: dict | None = None) -> str | None:
    """One OpenRouter chat completion. Returns content, or None on any
    failure (missing config, network, upstream error). Never raises —
    callers fall back to deterministic behavior."""
    key = config.OPENROUTER_API_KEY
    model = config.ASK_ENDPOINT_MODEL
    if not key or not model:
        return None

    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }
    if response_format:
        payload["response_format"] = response_format

    try:
        resp = httpx.post(
            f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": config.FRONTEND_URL or "https://persona.zynd.ai",
                "X-Title": "Zynd Public Ask",
            },
            json=payload,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        resp.raise_for_status()
        choices = (resp.json() or {}).get("choices") or []
        if choices:
            return choices[0].get("message", {}).get("content") or None
        return None
    except Exception as exc:
        logger.warning("[public-ask] OpenRouter call failed: %s", exc)
        return None


_PARSE_SYSTEM = (
    "You extract search parameters from a natural-language request about "
    "finding people on the Zynd AI persona network. Respond with ONLY a "
    "JSON object: {\"query\": \"<trimmed topic, role, or description "
    "keywords>\", \"mode\": \"domain\" | \"similar\"}. Use mode \"similar\" "
    "ONLY when the request describes a specific person profile to match "
    "('people similar to me, I am ...', 'someone like X'). Otherwise use "
    "mode \"domain\". The query must be the cleaned keywords only — no "
    "verbs like 'find' or 'search'."
)


def _llm_parse(question: str) -> tuple[str, str] | None:
    """LLM maps the question to (query, mode); None on failure/absence."""
    content = _openrouter_chat(
        [
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": question},
        ],
        response_format={"type": "json_object"},
    )
    if not content:
        return None
    try:
        data = json.loads(content)
        mode = str(data.get("mode", "domain")).lower().strip()
        query = str(data.get("query", "")).strip()
        if query and mode in ("domain", "similar"):
            return query, mode
    except Exception as exc:
        logger.warning("[public-ask] LLM parse JSON invalid: %s", exc)
    return None


def _heuristic_parse(question: str) -> tuple[str, str]:
    """Deterministic fallback: similarity markers → similar, else domain.
    The search backends strip stopwords themselves, so pass the question
    through mostly as-is (trimmed)."""
    low = (question or "").lower()
    mode = "similar" if any(m in low for m in _SIMILAR_MARKERS) else "domain"
    return question.strip(), mode


def _llm_answer(question: str, mode: str, results: list[dict]) -> str | None:
    """LLM-written natural summary of the results; None on failure."""
    if not results:
        return None
    digest = [
        {
            "name": r.get("name") or "",
            "description": (r.get("description") or "")[:200],
            "match_reason": r.get("match_reason") or "",
        }
        for r in results[:5]
    ]
    system = (
        "You are the assistant on the Zynd AI persona network. Write a "
        "short, friendly 2-4 sentence answer telling the user which people "
        "were found, what each one does (from description), and why they "
        "matched. No markdown, no bullet lists. Plain text."
    )
    return _openrouter_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(
                {"question": question, "mode": mode, "found": digest},
                ensure_ascii=False,
            )},
        ]
    )


def _deterministic_answer(mode: str, results: list[dict]) -> str:
    """Format a plain answer from results — no LLM."""
    if not results:
        return "I couldn't find anyone on Zynd matching that."
    names = []
    for r in results[:5]:
        name = r.get("name") or "Someone"
        desc = (r.get("description") or "").strip().split(".")[0]
        names.append(f"{name} ({desc})" if desc else name)
    intro = (
        f"Found {len(results)} {'similar' if mode == 'similar' else ''} "
        f"people on Zynd"
    ).replace("  ", " ")
    return f"{intro}: " + "; ".join(names) + "."


# ── Endpoint ─────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=200)
    mode: Literal["domain", "similar"] | None = None
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=40)


async def _handle_ask(question: str, mode: str | None, limit: int) -> dict:
    question = question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    parsed = None
    if mode is None:
        parsed = await asyncio.to_thread(_llm_parse, question)
    if parsed:
        query, mode = parsed
    else:
        query, mode = _heuristic_parse(question)

    if mode == "similar":
        result = await asyncio.to_thread(search_similar_people, query, limit)
    else:
        result = await asyncio.to_thread(search_zynd_personas, query, limit, "", False, False)

    results = result.get("results") or []

    answer = None
    if results:
        answer = await asyncio.to_thread(_llm_answer, question, mode, results)
    if not answer:
        answer = _deterministic_answer(mode, results)

    return {
        "question": question,
        "answer": answer,
        "mode": mode,
        "query_used": query,
        "status": result.get("status", "success"),
        "count": result.get("count", len(results)),
        "total_available": result.get("total_available", len(results)),
        "source": result.get("source", ""),
        "results": results,
    }


@router.post("/ask")
async def ask_post(req: AskRequest, request: Request):
    """Ask in plaintext ('find me AI founders'); get a natural answer +
    structured results. Public — rate limited per IP."""
    if _rate_limited(_client_ip(request), _ASK_HITS, _ASK_WINDOW_SECONDS, _ASK_MAX_PER_WINDOW):
        raise HTTPException(status_code=429, detail="Too many requests — slow down.")
    return await _handle_ask(req.question, req.mode, req.limit)


@router.get("/ask")
async def ask_get(
    request: Request,
    question: str = Query(..., min_length=1, max_length=200),
    mode: Literal["domain", "similar"] | None = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=40),
):
    """GET variant — browsable by ChatGPT's GET-only browser tool."""
    if _rate_limited(_client_ip(request), _ASK_HITS, _ASK_WINDOW_SECONDS, _ASK_MAX_PER_WINDOW):
        raise HTTPException(status_code=429, detail="Too many requests — slow down.")
    return await _handle_ask(question, mode, limit)