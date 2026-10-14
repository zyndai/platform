"""Unit tests for the v2 predicate taxonomy (36 original + uses_tool)."""
from app.taxonomy import (ALLOWED_PREDICATES, INFERRABLE_PREDICATES, SYSTEM_PREDICATES,
                          DECLARED_ONLY, FINDABILITY_PREDICATES, MATCHING_PREDICATES,
                          decay_fn_for)


def test_thirtyseven_predicates():
    assert len(ALLOWED_PREDICATES) == 37
    assert "uses_tool" in ALLOWED_PREDICATES


def test_system_and_declared_only_excluded_from_extraction():
    assert "is_resolved" in SYSTEM_PREDICATES and "is_resolved" not in INFERRABLE_PREDICATES
    assert "open_to" in DECLARED_ONLY and "open_to" not in INFERRABLE_PREDICATES
    assert len(INFERRABLE_PREDICATES) == 35


def test_findability_is_subset_of_all():
    assert FINDABILITY_PREDICATES <= ALLOWED_PREDICATES


def test_card_only_sections_are_public_but_not_matched():
    # Working-on and tools get their own public card rows...
    assert {"is_working_on", "uses_tool"} <= FINDABILITY_PREDICATES
    # ...but must not change who matches whom.
    assert not ({"is_working_on", "uses_tool"} & MATCHING_PREDICATES)
    assert MATCHING_PREDICATES <= FINDABILITY_PREDICATES


def test_extraction_prompt_teaches_tools_vs_building():
    from app.services.extraction import SYSTEM_PROMPT
    assert "uses_tool" in SYSTEM_PROMPT
    assert "never is_building" in SYSTEM_PROMPT


def test_uses_tool_decays_slowly():
    assert decay_fn_for("uses_tool") == "exponential(halflife=365d)"


def test_new_predicates_have_decay():
    assert decay_fn_for("is_resolved") == "exponential(halflife=180d)"
    assert decay_fn_for("has_unsolved_problem") == "none"
    assert decay_fn_for("is_motivated_by") == "exponential(halflife=365d)"
