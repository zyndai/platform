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
    assert r.suggested_predicate == "uses_tool"


def test_codex_reported_as_project_is_retyped_to_tool():
    # Regression: Codex and Claude in Chrome were landing under "Currently building".
    for name in ("Codex", "Claude in Chrome"):
        r = assess(name, intended_predicate="is_building", field="projects")
        assert r.group == "look"
        assert r.suggested_predicate == "uses_tool"


def test_tools_field_keeps_uses_tool_and_labels_it():
    r = assess("Codex", intended_predicate="uses_tool", field="tools")
    assert r.group == "right"
    assert r.suggested_predicate == "uses_tool"
    assert r.public_label == "Uses: Codex"


def test_working_on_is_not_folded_into_building():
    from app.services.quality import public_predicate_for
    assert public_predicate_for("is_working_on") == "is_working_on"
    assert surface_dedupe_key("is_working_on", "SendPilot") != surface_dedupe_key(
        "is_building", "sendpilot",
    )
    assert public_label_for("is_working_on", "SendPilot") == "Working on: SendPilot"


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
