"""Unit tests for the v2 sensitive-gate scanner (no LLM/DB)."""
from app.services.gates import detect_gates, is_gated


def test_detect_gates_finds_signals():
    assert detect_gates("I saw my doctor about anxiety") == {"health"}
    assert detect_gates("thinking about the election and who to vote for") == {"politics"}
    assert detect_gates("my visa and green card situation") == {"immigration"}
    assert detect_gates("I am building a Rust marketplace") == set()


def test_is_gated_withholds_guarded_predicates():
    assert is_gated("believes", {"politics"}) is True          # belief gated by politics
    assert is_gated("believes", {"health"}) is False           # wrong gate -> allowed
    assert is_gated("is_located_in", {"immigration"}) is True
    assert is_gated("is_navigating", {"health"}) is True       # health/imm -> either
    assert is_gated("is_building", {"politics", "health"}) is False  # ungated, always allowed
