"""Unit tests for the v2 35-predicate taxonomy."""
from app.taxonomy import (ALLOWED_PREDICATES, INFERRABLE_PREDICATES, SYSTEM_PREDICATES,
                          DECLARED_ONLY, FINDABILITY_PREDICATES, decay_fn_for)


def test_thirtyfive_predicates():
    assert len(ALLOWED_PREDICATES) == 35


def test_system_and_declared_only_excluded_from_extraction():
    assert "is_resolved" in SYSTEM_PREDICATES and "is_resolved" not in INFERRABLE_PREDICATES
    assert "open_to" in DECLARED_ONLY and "open_to" not in INFERRABLE_PREDICATES
    assert len(INFERRABLE_PREDICATES) == 33


def test_findability_is_subset_of_all():
    assert FINDABILITY_PREDICATES <= ALLOWED_PREDICATES


def test_new_predicates_have_decay():
    assert decay_fn_for("is_resolved") == "exponential(halflife=180d)"
    assert decay_fn_for("has_unsolved_problem") == "none"
    assert decay_fn_for("is_motivated_by") == "exponential(halflife=365d)"
