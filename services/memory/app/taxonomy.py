"""Single source of truth for predicates, decay, entity types, and clusters.

Brief §14.8: a new predicate requires a migration + prompt update + decay_fn.
Adding one here (and to the extraction prompt) is that change in one place.
"""

# Predicate -> decay half-life in days. None = no decay. (Brief §4.)
PREDICATE_HALFLIFE_DAYS: dict[str, int | None] = {
    "is_learning": 30,
    "has_expertise_in": 540,        # 18 months
    "is_building": 60,
    "is_working_on": 14,
    "intends_to": 21,
    "believes": 90,
    "values": 365,
    "is_located_in": None,
    "is_affiliated_with": None,
    "is_frustrated_by": 45,
    "is_inspired_by": 180,           # 6 months
    "has_skill": 730,                # 2 years
    "recently_changed_stance_on": 30,
    "is_seeking": 7,
    "has_collaborator": None,
    "open_to": None,                 # declared availability (coffee, collab, mentoring) — no decay
}

ALLOWED_PREDICATES: frozenset[str] = frozenset(PREDICATE_HALFLIFE_DAYS)

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
