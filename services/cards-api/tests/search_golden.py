"""Golden-query harness for card search (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md §13).

Loads fixtures/search_golden.json (a synthetic corpus plus hand-labelled queries), runs
`search_agents` over it with a hashed bag-of-words embedder, and reports:

  precision@k = relevant people in the top k / k,  k = min(5, number of relevant people)
  recall@5    = relevant people found in the top 5 / min(5, relevant people)

Run `python tests/search_golden.py` for the per-query table while tuning scoring.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import math
import pathlib
import re
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "search_golden.json"
DIM = 256


def hash_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
        digest = hashlib.md5(token.encode()).digest()
        vec[int.from_bytes(digest[:4], "big") % DIM] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


@dataclass
class QueryResult:
    target: str
    relevant: list[str]
    top: list[str]
    precision: float
    recall: float


def load() -> dict:
    return json.loads(FIXTURE.read_text())


def build_rows(doc: dict) -> list[dict]:
    from datetime import datetime, timezone

    from models.card import AgentProfileCard
    from services.embed import card_search_text

    rows = []
    for c in doc["cards"]:
        card = AgentProfileCard(
            id=f"id-{c['handle']}", status="published", handle=c["handle"],
            identity={"name": c["handle"], "headline": c["headline"], "location": c["location"],
                      "avatar_url": "", "links": {}},
            summary=c["summary"], skills=[{"name": s} for s in c["skills"]], industries=c["industries"],
            connect_with=c.get("connect_with", []),
            zynd_memory=[{"predicate": "is_building", "object": o, "source": "declared",
                          "approved_at": datetime.now(timezone.utc).isoformat(), "confidence": 0.9}
                         for o in c["memory"]],
        )
        rows.append({"card": card.model_dump(mode="json"), "handle": c["handle"],
                     "owner_email": "owner@example.com",
                     "embedding": hash_embed(card_search_text(card))})
    return rows


def evaluate(doc: dict | None = None, search_service=None) -> list[QueryResult]:
    from unittest.mock import MagicMock, patch

    if search_service is None:
        from services import search as search_service

    logging.getLogger("services.search").setLevel(logging.ERROR)   # one 'falling back' warning per query
    doc = doc or load()
    rows = build_rows(doc)
    from models.card import AgentProfileCard
    cards_by_handle = {r["handle"]: AgentProfileCard.model_validate(r["card"]) for r in rows}
    for handle, card in cards_by_handle.items():
        card.handle = handle
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc: score the whole corpus")
    out: list[QueryResult] = []
    with patch.object(search_service.config, "get_supabase", lambda: sb), \
         patch.object(search_service, "embed_text", hash_embed), \
         patch.object(search_service.cards_service, "list_published_rows", lambda **kw: rows):
        for query in doc["queries"]:
            extra = {}
            if "searcher" in inspect.signature(search_service.search_agents).parameters:   # older scorers lack it
                extra["searcher"] = cards_by_handle.get(query.get("as_handle") or "")
            found = search_service.search_agents(
                q=query["q"], role=query["role"], location=query["location"],
                skills=query["skills"], limit=5, include_unclaimed=True, **extra)
            top = [r["handle"] for r in found]
            relevant = query["relevant"]
            if relevant:
                k = min(5, len(relevant))
                precision = len([h for h in top[:k] if h in relevant]) / k
                recall = len([h for h in top if h in relevant]) / k
            else:
                # nothing should match: success is an empty result
                precision = recall = 1.0 if not top else 0.0
            out.append(QueryResult(query["target"], relevant, top, precision, recall))
    return out


def summarize(results: list[QueryResult]) -> dict:
    n = len(results)
    return {"queries": n,
            "precision_at_k": sum(r.precision for r in results) / n,
            "recall_at_5": sum(r.recall for r in results) / n}


if __name__ == "__main__":
    results = evaluate()
    for r in results:
        flag = "ok " if r.precision == 1.0 and r.recall == 1.0 else "-- "
        print(f"{flag}p={r.precision:.2f} r={r.recall:.2f}  {r.target!r}\n      want={r.relevant}\n      got ={r.top}")
    print(summarize(results))
