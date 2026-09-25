"""
Regression tests for persona search ranking (`_match_score` in
mcp/tools/zynd_network.py).

The old scorer ranked purely by raw keyword-overlap count, so for a query
like "AI founders" a developer whose bio just mentioned "AI" once could
rank alongside (or crowd out) an actual founder, since neither needed to
match every concept in the query to place well. The new scorer ranks
primarily by concept *coverage* so full matches always beat partial ones,
and explains partial matches honestly instead of overselling them.
"""

from __future__ import annotations

from mcp.tools.zynd_network import _match_score


def test_full_coverage_outranks_partial_coverage():
    # "AI founders" -> concepts {ai, founder}. The founder matches both;
    # the developer only matches "ai".
    founder_score, founder_reason = _match_score(
        "AI founders",
        name="Priya Shah",
        description="Co-founder and CEO building an AI infrastructure startup.",
    )
    developer_score, developer_reason = _match_score(
        "AI founders",
        name="Alex Kim",
        description="Software developer working on AI tooling.",
    )
    assert founder_score > developer_score
    assert "missing" not in founder_reason
    assert "missing: founder" in developer_reason


def test_no_overlap_scores_zero_with_empty_reason():
    score, reason = _match_score("AI founders", name="Jamie Lee", description="Loves painting and travel.")
    assert score == 0
    assert reason == ""


def test_single_concept_query_has_no_missing_suffix():
    # A one-token query has nothing to be "partial" about.
    score, reason = _match_score("designer", name="Sam", description="Product designer at a fintech startup.")
    assert score > 0
    assert "missing" not in reason


def test_tag_and_name_hits_break_ties_within_same_coverage():
    # Both fully cover the query ("ai"), so coverage ties — the one with
    # the concept in a curated field (tags) should score higher than one
    # where it's only buried in free-text description.
    tag_score, _ = _match_score("ai", name="Riley", description="Works in tech.", tags=["ai"])
    desc_only_score, _ = _match_score("ai", name="Riley", description="Occasionally reads about AI news.")
    assert tag_score > desc_only_score


def test_cofounder_compound_word_matches_bare_founder_query():
    # Real-data regression: a persona whose bio says "looking for a
    # technical cofounder" is exactly who an "AI founders" search should
    # surface, but an exact-stem lookup treats "cofounder" as a totally
    # different word from "founder" and silently zeroed them out.
    score, reason = _match_score(
        "AI founders",
        name="Sye",
        description="Building an AI memory layer. Looking for a technical cofounder.",
    )
    assert "missing" not in reason
    assert "cofounder" in reason


def test_short_query_token_does_not_suffix_match_unrelated_words():
    # "ai" is only 2 chars — must NOT suffix-match into unrelated words
    # like "mumbai" (the compound-word fallback is gated to 4+ char tokens
    # specifically to prevent this).
    score, reason = _match_score("ai", name="Dev", description="Based in Mumbai, working in fintech.")
    assert score == 0
    assert reason == ""
