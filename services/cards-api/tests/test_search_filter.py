"""Filtered searches read only the cards that could pass, from cards.filter_cards (migration
0030), and that filter must never drop a card the exact rules in Constraints.matches keep."""
import json
import re
from unittest.mock import MagicMock

import pytest

from models.card import AgentProfileCard
from services import search as S
from services.search_constraints import Constraints
from tests import search_golden


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", text.lower())


def sql_keeps(card: dict, role_groups, place, skill_groups) -> bool:
    """cards.filter_cards's WHERE clause, in Python."""
    everything = squash(json.dumps(card))
    where = squash(((card.get("identity") or {}).get("location")) or "")
    return (all(any(f in everything for f in g) for g in role_groups if g)
            and all(any(f in everything for f in g) for g in skill_groups if g)
            and (not place or any(f in where for f in place)))


def test_groups_hold_every_spelling_the_exact_rules_accept():
    role, place, skills = S.filter_groups("investor", "India", ("js",))
    assert {"investor", "vc", "venture", "angel"} <= set(role[0])
    assert {"india", "pune", "gurgaon", "bangalore", "bengaluru"} <= set(place)
    assert {"javascript", "js"} <= set(skills[0])
    assert S.filter_groups("founder", "", ())[0][0][-1] == "isfounderof"
    _, place, _ = S.filter_groups("", "Bengaluru", ())
    assert {"bangalore", "bengaluru"} <= set(place) and "india" not in place, "a city is not widened"
    assert S.filter_groups("", "", ()) == ([], [], [])


CASES = [
    ("investor", "India", ()), ("investors", "Gurgaon", ()), ("founder", "", ()), ("engineer", "Bangalore", ("rust",)),
    ("", "Bengaluru", ()), ("", "New York", ()), ("developer", "", ("nextjs",)), ("", "", ("javascript",)),
    ("recruiter", "United Kingdom", ()), ("lawyer", "Pune", ()), ("designer", "", ("figma",)),
]


def test_the_database_filter_never_drops_a_card_the_exact_rules_keep():
    rows = search_golden.build_rows(search_golden.load())
    extra = [
        {"identity": {"headline": "Builder", "location": "Bengaluru, Karnataka"}, "skills": [{"name": "JS"}]},
        {"identity": {"headline": "Engineer", "location": "NYC"}, "skills": [{"name": "Next.js"}, {"name": "Node.js"}]},
        {"identity": {"headline": "Cofounder & CEO", "location": "Pune"}, "skills": [{"name": "C++"}]},
        {"identity": {"headline": "VC", "location": "Gurugram, Haryana"}, "skills": []},
    ]
    cards = [r["card"] for r in rows] + [AgentProfileCard(id=f"x{i}", status="published", **c).model_dump(mode="json")
                                         for i, c in enumerate(extra)]
    kept_by_filter = checked = 0
    for role, location, skills in CASES + [("", "", ("js",)), ("", "", ("c++",)), ("founder", "Pune", ("c++",))]:
        groups = S.filter_groups(role, location, skills)
        constraints = Constraints(role, location, skills)
        for card in cards:
            if constraints.matches(AgentProfileCard.model_validate(card)):
                checked += 1
                assert sql_keeps(card, *groups), (role, location, skills, card["identity"])
                kept_by_filter += 1
    assert checked > 20 and kept_by_filter == checked


@pytest.fixture
def db(monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(S.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(S, "embed_text", lambda q: [1.0, 0.0])
    full_scan = MagicMock(side_effect=AssertionError("filtered search must not read every card"))
    monkeypatch.setattr(S.cards_service, "list_published_rows", full_scan)
    return sb, full_scan


def _db_row(handle, headline, location, similarity=0.5):
    card = AgentProfileCard(id=f"id-{handle}", status="published", handle=handle,
                            identity={"name": handle, "headline": headline, "location": location, "avatar_url": "", "links": {}})
    return {"id": card.id, "handle": handle, "card": card.model_dump(mode="json"), "similarity": similarity, "claimed": True}


def test_a_filtered_search_asks_the_database_for_survivors_only(db):
    sb, _ = db
    sb.rpc.return_value.execute.return_value.data = [_db_row("vc", "Seed investor", "Pune")]
    found = S.search_agents(q="investor in Pune", role="investor", location="Pune", include_unclaimed=True)
    assert [r["handle"] for r in found] == ["vc"]
    name, args = sb.rpc.call_args.args
    assert name == "filter_cards" and args["query_embedding"] == [1.0, 0.0] and args["include_unclaimed"] is True
    assert args["p_location"] == ["pune"] and "vc" in args["p_role"][0]


def test_every_relaxed_pass_asks_for_its_own_rows(db):
    """Dropping the location must widen what is read, not rescore the strict pass's rows."""
    sb, _ = db
    calls = []

    def rpc(name, args):
        if name != "filter_cards":
            return MagicMock(execute=lambda: MagicMock(data=[]))
        calls.append((args["p_role"] != [], args["p_location"]))
        data = [_db_row("vc", "Seed investor", "Paris")] if not args["p_location"] else []
        return MagicMock(execute=lambda: MagicMock(data=data))
    sb.rpc.side_effect = rpc
    found = S.search_agents(q="investor", role="investor", location="Pune", relax=True, include_unclaimed=True)
    assert [r["handle"] for r in found] == ["vc"] and found[0]["relaxed"] == ["location"]
    assert calls[0][1] == ["pune"] and calls[-1][1] == [] and len(calls) >= 3


def test_a_missing_function_falls_back_to_reading_every_card(monkeypatch):
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("function cards.filter_cards does not exist")
    monkeypatch.setattr(S.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(S, "embed_text", lambda q: [])
    rows = [{"card": _db_row("vc", "Seed investor", "Pune")["card"], "handle": "vc", "owner_email": "o@x.co"}]
    monkeypatch.setattr(S.cards_service, "list_published_rows", lambda **kw: rows)
    assert [r["handle"] for r in S.search_agents(q="investor", role="investor", location="Pune")] == ["vc"]


def test_a_filter_that_returns_the_cap_is_not_trusted(monkeypatch):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = [_db_row(f"c{i}", "Investor", "Pune") for i in range(3)]
    monkeypatch.setattr(S.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(S, "embed_text", lambda q: [])
    monkeypatch.setattr(S, "FILTERED_ROWS_LIMIT", 3)
    scanned = []
    monkeypatch.setattr(S.cards_service, "list_published_rows", lambda **kw: scanned.append(1) or [])
    assert S.search_agents(q="investor", role="investor", location="Pune") == [] and scanned


def test_industry_and_availability_are_not_in_the_database_filter(db):
    sb, full_scan = db
    full_scan.side_effect = None
    full_scan.return_value = []
    S.search_agents(q="investor", role="investor", industry="fintech")
    assert not [c for c in sb.rpc.call_args_list if c.args[0] == "filter_cards"]
