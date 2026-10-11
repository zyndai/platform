"""Pure-function tests for S05 inbox quality scoring."""
from app.services.quality import (
    assess,
    assess_typed_field,
    canonicalize,
    dedupe_suggestion_rows,
    public_label_for,
    surface_dedupe_key,
)


def test_canonicalize_collapses_whitespace_and_quotes():
    assert canonicalize('  "Claude   Code"  ') == "Claude Code"
    assert canonicalize("") == ""


def test_tools_assess_as_right_has_skill():
    r = assess("Claude Code", intended_predicate="has_skill", field="tools")
    assert r.group == "right"
    assert r.suggested_predicate == "has_skill"
    assert r.drop is False
    assert "Expert in" in r.public_label


def test_repo_like_is_noise():
    r = assess("acme/zynd-platform", intended_predicate="is_building", field="projects")
    assert r.group == "noise"
    assert r.reason == "repo_or_path"


def test_worker_trees_is_noise():
    r = assess("worker trees", intended_predicate="is_responsible_for", field="projects")
    assert r.group == "noise"
    assert r.reason == "internal_jargon"


def test_tool_as_project_needs_look_and_retypes():
    r = assess("Docker", intended_predicate="is_building", field="projects")
    assert r.group == "look"
    assert r.suggested_predicate == "has_skill"


def test_generic_token_is_noise():
    r = assess("ai", intended_predicate="has_skill", field="skills")
    assert r.group == "noise"


def test_assess_typed_field_dedupes_case():
    results = assess_typed_field(
        "tools", ["Claude Code", "claude code", "SendPilot"], predicate="has_skill",
    )
    assert [r.value for r in results] == ["Claude Code", "SendPilot"]


def test_public_label_building_is_object_only():
    assert public_label_for("is_building", "SendPilot") == "SendPilot"
    assert public_label_for("has_skill", "Rust") == "Expert in: Rust"


def test_surface_dedupe_collapses_approve_family():
    assert surface_dedupe_key("has_skill", "Stocks") == surface_dedupe_key(
        "has_expertise_in", "stocks",
    )


def test_dedupe_suggestion_rows_keeps_first():
    rows = [
        {"predicate": "has_skill", "object": "Stocks", "group": "right", "confidence": 0.9},
        {"predicate": "has_expertise_in", "object": "stocks", "group": "look", "confidence": 0.8},
    ]
    out = dedupe_suggestion_rows(rows)
    assert len(out) == 1
    assert out[0]["predicate"] == "has_skill"
