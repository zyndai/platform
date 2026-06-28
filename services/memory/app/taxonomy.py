"""Single source of truth for predicates, decay, entity types, and clusters.

Brief §14.8: a new predicate requires a migration + prompt update + decay_fn.
Adding one here (and to the extraction prompt) is that change in one place.
"""

# Predicate -> decay half-life in days. None = no decay. (v2 predicate reference, 35 total.)
PREDICATE_HALFLIFE_DAYS: dict[str, int | None] = {
    # 1. Building & creating
    "is_building": 60,
    "is_working_on": 14,
    "is_creating": 60,
    "wants_to_preserve": 365,
    # 2. Learning & skills
    "is_learning": 30,
    "has_expertise_in": 540,         # 18 months
    "has_skill": 730,                # 2 years
    # 3. Goals & intent
    "intends_to": 21,
    "is_seeking": 7,
    "is_preparing_for": 14,
    "fears": 30,
    "open_to": None,                 # declared availability — no decay
    # 4. Beliefs & values
    "believes": 90,
    "values": 365,
    "recently_changed_stance_on": 30,
    "has_aesthetic": 365,
    # 5. Navigation & constraints
    "is_navigating": 60,
    "is_constrained_by": 45,
    "is_frustrated_by": 45,
    "has_been_wronged": 180,         # 6 months
    "is_resolved": 180,              # system-emitted only
    # 6. Life stage & experience
    "is_transitioning": 180,
    "is_experiencing": 90,
    "is_processing": 45,
    "is_rediscovering": 365,
    "has_unsolved_problem": None,
    # 7. Relationships & responsibilities
    "has_collaborator": None,
    "is_responsible_for": None,
    "is_advocating_for": 180,
    "is_in_conflict_with": 90,
    "is_inspired_by": 180,
    # 8. Place & affiliation
    "is_located_in": None,
    "is_affiliated_with": None,
    "has_language_context": None,
    # 9. Motivation
    "is_motivated_by": 365,
}

ALLOWED_PREDICATES: frozenset[str] = frozenset(PREDICATE_HALFLIFE_DAYS)

# System-emitted (never extracted or declared) + declared-only predicates.
SYSTEM_PREDICATES: frozenset[str] = frozenset({"is_resolved"})
DECLARED_ONLY: frozenset[str] = frozenset({"open_to"})
# What the LLM extractor is allowed to emit (v2 source = inferred|both).
INFERRABLE_PREDICATES: frozenset[str] = ALLOWED_PREDICATES - SYSTEM_PREDICATES - DECLARED_ONLY

# v2 — the ONLY predicates used for matching / public discovery (the "findability card").
# Everything else (beliefs, frustrations, life-stage, etc.) is private memory, never matched.
FINDABILITY_PREDICATES: frozenset[str] = frozenset({
    "is_building", "is_learning", "has_expertise_in",
    "is_seeking", "open_to", "is_affiliated_with", "is_located_in",
})

# Entity subtypes by family (brief §2). Flattened to a validation set.
ENTITY_TYPES: frozenset[str] = frozenset({
    "self", "collaborator", "influence", "adversary",
    "place_physical", "place_institutional", "place_virtual",
    "concept_field", "concept_topic", "concept_idea",
    "project_venture", "project_assignment", "project_side",
    "skill_technical", "skill_cognitive", "skill_domain",
    "belief_opinion", "belief_value", "belief_worldmodel",
    "intent_immediate", "intent_project", "intent_life",
    "artifact_document", "artifact_code", "artifact_creative",
})

# Cluster -> predicates it is built from. v2: every match cluster draws ONLY from
# FINDABILITY_PREDICATES — beliefs, frustrations, and life-stage are never matched on.
CLUSTER_PREDICATES: dict[str, frozenset[str]] = {
    "intent_cluster": frozenset({"is_building", "is_seeking", "open_to"}),
    "skill_cluster": frozenset({"has_expertise_in", "is_learning"}),
    "place_cluster": frozenset({"is_affiliated_with", "is_located_in"}),
    "full_context": FINDABILITY_PREDICATES,
}

# Reliability weight per source, used in the Bayesian update (brief §5.4).
SOURCE_RELIABILITY: dict[str, float] = {
    "user_confirmed": 1.00,
    "claude": 0.85,
    "chatgpt": 0.80,
    "import": 0.70,
}
DEFAULT_SOURCE_RELIABILITY = 0.70


def decay_fn_for(predicate: str) -> str:
    """Canonical decay_fn string for a predicate. Derived here, not trusted
    from the LLM (brief §14.3: never write LLM output straight to the DB)."""
    halflife = PREDICATE_HALFLIFE_DAYS[predicate]
    return "none" if halflife is None else f"exponential(halflife={halflife}d)"
