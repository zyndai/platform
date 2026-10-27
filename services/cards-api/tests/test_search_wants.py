"""Who someone wants to meet is not who they are (people search quality plan, E1), and a topic of
several words matches as a phrase (E2)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.card import AgentProfileCard
from services import search as S
from services.embed import card_search_text, is_wants_fact
from services.search_text import phrase_score, term_sequence, topic_phrases, topic_terms
from services.two_way import wanted_kinds

WANTS = "Mahesh — looking to connect with Founders, Investors, Engineers — Zynd"


def _card(handle, *, headline, facts=(), connect_with=(), memory=(), summary=""):
    now = datetime.now(timezone.utc).isoformat()
    return AgentProfileCard(
        id=f"id-{handle}", status="published", handle=handle,
        identity={"name": handle.title(), "headline": headline, "location": "Pune, India", "avatar_url": "", "links": {}},
        summary=summary, searchable_facts=list(facts), connect_with=list(connect_with),
        zynd_memory=[{"predicate": p, "object": o, "source": "declared", "approved_at": now, "confidence": 0.9}
                     for p, o in memory],
    )


@pytest.fixture
def corpus(monkeypatch):
    rows: list[dict] = []
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc")
    monkeypatch.setattr(S.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(S, "embed_text", lambda q: [1.0, 0.0])
    monkeypatch.setattr(S.cards_service, "list_published_rows", lambda **kw: rows)
    return rows


def _row(card, similarity=0.5):
    return {"card": card.model_dump(mode="json"), "handle": card.handle, "owner_email": "o@example.com",
            "similarity": similarity}


def test_the_wants_to_meet_fact_is_recognised():
    assert is_wants_fact(WANTS)
    assert is_wants_fact("Bo - wants to meet investors")
    assert is_wants_fact("looking to connect with Founders")
    assert not is_wants_fact("Mahesh — working on AI agents — Zynd")
    assert not is_wants_fact("Mahesh — loves talking about investing — Zynd")


def test_the_person_text_leaves_out_who_they_want_to_meet_and_what_they_seek():
    card = _card("mahesh", headline="Software developer", facts=[WANTS, "Mahesh — working on AI agents — Zynd"],
                 memory=[("is_seeking", "investors"), ("is_building", "an agents SDK")])
    text = card_search_text(card).lower()
    assert "investor" not in text
    assert "working on ai agents" in text and "an agents sdk" in text


def test_two_way_matching_still_sees_the_wish():
    card = _card("mahesh", headline="Software developer", facts=[WANTS], connect_with=["Investors"])
    assert "Investors" in wanted_kinds(card)


def test_wanting_investors_does_not_make_a_developer_an_investor(corpus):
    corpus += [_row(_card("mahesh", headline="Software developer", facts=[WANTS], connect_with=["Investors"],
                          memory=[("is_seeking", "investors")]), similarity=0.55),
               _row(_card("vc", headline="Seed investor"), similarity=0.45)]
    found = {r["handle"]: r for r in S.search_agents(q="investor in India", role="investor", location="India",
                                                     relax=True, include_unclaimed=True)}
    assert "Role match" not in found["mahesh"]["match_reasons"]
    assert found["mahesh"]["relaxed"] == ["location", "role"]
    assert found["mahesh"]["match_score"] < 0.5 <= found["vc"]["match_score"]


def test_a_multi_word_topic_matches_as_a_phrase():
    devtools = term_sequence("Building open-source developer tools for teams")
    dev_only = term_sequence("Software developer, Next.js development")
    assert phrase_score(devtools, topic_terms("developer tools")) == 1.0
    assert phrase_score(term_sequence("devtools"), topic_terms("developer tools")) == 1.0
    assert phrase_score(term_sequence("tools for developers"), topic_terms("developer tools")) == 1.0
    assert phrase_score(dev_only, topic_terms("developer tools")) == 0.0, "generic words alone earn nothing"
    assert phrase_score(dev_only, topic_terms("AI development")) == 0.0
    assert phrase_score(term_sequence("climate investor"), topic_terms("climate hardware")) == 0.25


def test_lone_generic_topics_and_ones_the_query_already_says_are_not_scored():
    assert topic_phrases("tools, software") == []
    assert [label for label, _ in topic_phrases("developer tools, AI")] == ["developer tools", "AI"]
    already = {t for q in ("ai", "dev", "tool") for t in topic_terms(q)}
    assert topic_phrases("AI dev tools, developer tools", already) == []


def test_a_developer_is_not_credited_with_the_topic_developer_tools(corpus):
    corpus += [_row(_card("dev", headline="Software developer", summary="Next.js development"), similarity=0.5),
               _row(_card("tools", headline="Engineer", summary="Builds developer tools"), similarity=0.5)]
    found = {r["handle"]: r for r in S.search_agents(q="engineer", topics="developer tools", include_unclaimed=True)}
    assert not any(str(x).startswith("Mentions") for x in found["dev"]["match_reasons"])
    assert "Mentions developer tools" in found["tools"]["match_reasons"]
    assert found["tools"]["match_score"] > found["dev"]["match_score"]


def test_a_wish_written_in_the_summary_is_not_who_they_are():
    card = _card("k", headline="React engineer",
                 summary="Frontend dev, looking forward to meet builders, founders and investors and get hired. Loves React.")
    text = card_search_text(card).lower()
    assert "investor" not in text and "loves react" in text


def test_investing_as_an_interest_is_not_the_job_of_investor(corpus):
    from services.search_text import role_matches, token_set
    assert role_matches(token_set("Angel investing at Acme"), "investor")                 # a headline may say it so
    assert not role_matches(token_set("working on Investing, Design"), "investor", activities=False)
    assert role_matches(token_set("angel in 3 startups"), "investor", activities=False)   # a real synonym still counts
    corpus += [_row(_card("hobby", headline="Software developer", facts=["Hobby — working on Investing — Zynd"]),
                    similarity=0.95)]
    (found,) = S.search_agents(q="investor", role="investor", relax=True, include_unclaimed=True)
    assert "Role match" not in found["match_reasons"]
