from app.services.provenance import (
    EVIDENCE_MAX_CHARS,
    PROVENANCE_LABELS,
    evidence_excerpt,
    provenance_for,
)


def test_agent_report_stays_agent_after_approval():
    # Approving rewrites the assertion's source_system to user_confirmed; the chunk
    # keeps the original, so the card can still say an agent reported it.
    assert provenance_for("user_confirmed", "declared", chunk_source_system="cards_mcp") == "agent"


def test_declared_with_no_chunk_is_you():
    assert provenance_for("user_confirmed", "declared") == "you"
    assert provenance_for(None, "declared") == "you"


def test_profile_chat_import_and_unknown():
    assert provenance_for("persona_seeded") == "profile"
    assert provenance_for("claude") == "chat"
    assert provenance_for("chatgpt") == "chat"
    assert provenance_for("import") == "import"
    assert provenance_for("something_new", "inferred") == "inferred"
    assert provenance_for(None, None) == "inferred"


def test_every_label_has_a_phrase():
    for label in {"you", "agent", "profile", "chat", "import", "inferred"}:
        assert PROVENANCE_LABELS[label]


def test_evidence_is_collapsed_and_clipped():
    assert evidence_excerpt("  The user   has a tool:\nCodex ") == "The user has a tool: Codex"
    assert evidence_excerpt("") is None
    assert evidence_excerpt(None) is None
    long = "x" * 500
    out = evidence_excerpt(long)
    assert len(out) == EVIDENCE_MAX_CHARS and out.endswith("…")
