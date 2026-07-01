"""Unit tests — pure logic, no I/O. Always runnable (no docker needed)."""
import math

import pytest

from app.models import ExtractedAssertion
from app.services.assertions import CONFIDENCE_CAP, bayesian_update
from app.services.mock_llm import mock_embed, mock_extract
from app.taxonomy import ALLOWED_PREDICATES, CLUSTER_PREDICATES, decay_fn_for


# ---- Bayesian update (brief §5.4) ----

def test_first_observation_discounts_by_source_reliability():
    # New assertion: prior 0 -> evidence * reliability.
    assert bayesian_update(0.0, 0.9, 0.8) == 0.72


def test_repeated_evidence_increases_confidence():
    assert bayesian_update(0.72, 0.9, 0.8) == 0.9216


def test_confidence_never_exceeds_cap():
    assert bayesian_update(0.95, 0.9, 1.0) == CONFIDENCE_CAP
    # Even after many strong observations it asymptotes, never reaching 1.0.
    conf = 0.0
    for _ in range(50):
        conf = bayesian_update(conf, 1.0, 1.0)
    assert conf == CONFIDENCE_CAP


def test_zero_evidence_leaves_prior_unchanged():
    assert bayesian_update(0.5, 0.0, 0.8) == 0.5


# ---- Decay function derivation (brief §4) ----

@pytest.mark.parametrize("predicate,expected", [
    ("is_working_on", "exponential(halflife=14d)"),
    ("is_learning", "exponential(halflife=30d)"),
    ("values", "exponential(halflife=365d)"),
    ("is_located_in", "none"),
    ("has_collaborator", "none"),
])
def test_decay_fn_for(predicate, expected):
    assert decay_fn_for(predicate) == expected


def test_every_predicate_has_a_decay_fn():
    for predicate in ALLOWED_PREDICATES:
        assert decay_fn_for(predicate)  # no KeyError, non-empty


# ---- Taxonomy consistency ----

def test_cluster_predicates_are_all_allowed():
    for cluster, predicates in CLUSTER_PREDICATES.items():
        assert predicates <= ALLOWED_PREDICATES, f"{cluster} has unknown predicates"


def test_full_context_covers_findability_predicates():
    from app.taxonomy import FINDABILITY_PREDICATES
    # v2: matching's full_context is the findability card, not every predicate.
    assert CLUSTER_PREDICATES["full_context"] == FINDABILITY_PREDICATES


# ---- LLM-output validation (brief §14.3) ----

def test_valid_assertion_passes():
    a = ExtractedAssertion(predicate="is_learning", object_name="Rust", object_type="skill_technical", confidence=0.9)
    assert a.predicate == "is_learning"


def test_unknown_predicate_rejected():
    with pytest.raises(ValueError):
        ExtractedAssertion(predicate="likes_pizza", object_name="x", object_type="skill_technical", confidence=0.9)


def test_unknown_entity_type_rejected():
    with pytest.raises(ValueError):
        ExtractedAssertion(predicate="is_learning", object_name="x", object_type="food", confidence=0.9)


def test_confidence_below_floor_rejected():
    with pytest.raises(ValueError):
        ExtractedAssertion(predicate="is_learning", object_name="x", object_type="skill_technical", confidence=0.4)


# ---- Mock extraction + hashing-trick embedding ----

def test_mock_extract_demo_sentence():
    text = "I am learning Rust async runtimes and building an ML marketplace. I intend to raise a seed round this year."
    out = {a.predicate: a.object_name for a in mock_extract(text)}
    assert out["is_learning"] == "Rust async runtimes"
    assert out["is_building"] == "ML marketplace"
    assert out["intends_to"] == "raise a seed round"


def test_mock_extract_empty_when_no_match():
    assert mock_extract("the weather is nice today") == []


def test_mock_embed_is_unit_length():
    vec = mock_embed("Rust async runtimes")
    assert len(vec) == 1536
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, abs_tol=1e-9)


def test_mock_embed_cosine_reflects_word_overlap():
    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    shared = cos(mock_embed("Rust async runtimes"), mock_embed("Rust async programming"))
    none = cos(mock_embed("Rust async runtimes"), mock_embed("baking sourdough bread"))
    assert shared > none
    assert math.isclose(none, 0.0, abs_tol=1e-9)
