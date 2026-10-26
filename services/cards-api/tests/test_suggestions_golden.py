"""Suggestions quality gate (D7): golden owners over the search golden corpus.

Each owner in fixtures/suggestions_golden.json is added to the search_golden.json corpus and run
through suggestions.compute with the same hashed embedder the search golden set uses. A change to
targets, the scorer or the merge that suggests the wrong kind of person fails here.

Run `python tests/test_suggestions_golden.py` to print each owner's suggestions while tuning.
"""
from __future__ import annotations

import json
import pathlib
import sys
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import search_golden  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "suggestions_golden.json"


def load() -> dict:
    return json.loads(FIXTURE.read_text())


def _owner_row(o: dict, n: int) -> dict:
    from models.card import AgentProfileCard

    card = AgentProfileCard(
        id=f"id-{o['handle']}", status="published", handle=o["handle"],
        identity={"name": o["handle"], "headline": o["headline"], "location": o.get("location", ""),
                  "avatar_url": "", "links": {}},
        connect_with=o.get("connect_with", []), working_on=o.get("working_on", []),
        love_talking_about=o.get("love_talking_about", []), skills=[{"name": s} for s in o.get("skills", [])],
    )
    return {"id": card.id, "handle": o["handle"], "status": "published", "owner_user_id": f"user-{n}",
            "owner_email": "owner@example.com", "card": card.model_dump(mode="json")}


def run() -> dict[str, list[dict]]:
    """owner handle -> suggestions, best first."""
    import config
    from services import search as search_service
    from services import suggestions
    from tests.fake_supabase import FakeSupabase

    doc = search_golden.load()
    corpus = search_golden.build_rows(doc)
    for i, r in enumerate(corpus):
        r.update(id=f"id-{r['handle']}", status="published", owner_user_id=f"corpus-{i}")
    out = {}
    for i, o in enumerate(load()["owners"]):
        owner = _owner_row(o, i)
        sb = FakeSupabase(agent_profile_cards=corpus + [owner])        # each owner on their own
        with patch.object(config, "get_supabase", lambda: sb), \
             patch.object(config, "FEATURE_NETWORK_CONTROLS", False), \
             patch.object(search_service, "embed_text", search_golden.hash_embed), \
             patch.object(search_service, "SEM_FLOOR", search_golden.HASH_SEM_FLOOR), \
             patch.object(search_service, "SEM_SPAN", search_golden.HASH_SEM_SPAN):
            out[owner["handle"]] = suggestions.compute(owner)
    return out


def test_golden_owners_get_the_people_they_asked_for():
    results = run()
    problems = []
    for o in load()["owners"]:
        got = [p["handle"] for p in results[o["handle"]]]
        if not got:
            problems.append(f"{o['handle']}: nobody")
            continue
        if o.get("first") and got[0] != o["first"]:
            problems.append(f"{o['handle']}: first {got[0]}, want {o['first']}")
        top = o.get("top") or []
        if top and not set(top) <= set(got[: len(top)]):
            problems.append(f"{o['handle']}: top {got[: len(top)]}, want {top}")
        wrong = [h for h in got[: o.get("kinds_in_first", 5)] if not any(h.startswith(k) for k in o["kinds"])]
        if wrong:
            problems.append(f"{o['handle']}: wrong kind {wrong}")
        never = set(o.get("never") or []) & set(got)
        if never:
            problems.append(f"{o['handle']}: never {sorted(never)}")
    assert not problems, "\n".join(problems)


if __name__ == "__main__":
    for owner, people in run().items():
        print(owner)
        for p in people[:6]:
            print(f"   {p['score']:.3f} {'2way ' if p['two_way'] else '     '}{p['handle']:<26} {p['why']}")
