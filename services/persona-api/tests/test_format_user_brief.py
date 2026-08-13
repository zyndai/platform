"""
Tests for `_format_user_brief` — the brief is now `persona.brief_content`
(plain text), falling back to `persona.description`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add backend/ to sys.path
_BACKEND_ROOT = Path("/home/ubuntu/agent-persona/backend")
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "TEST_TOKEN")

import config  # noqa: E402

config.get_supabase = MagicMock(return_value=MagicMock())

from agent import orchestrator  # noqa: E402

# Capture the real function at import time. `test_action_summary.py` patches
# `orchestrator._format_user_brief` without restoring it, so binding the
# reference here (collection runs before any test executes) keeps this test
# against the real implementation.
_format_user_brief = orchestrator._format_user_brief


def _persona(**overrides):
    persona = {
        "brief_content": "",
        "description": "Short pitch.",
        "profile": {
            "title": "Founder",
            "organization": "Acme",
            "location": "SF",
            "interests": ["AI", "chess"],
            "twitter": "@acme",
        },
    }
    persona.update(overrides)
    return persona


def test_brief_content_wins_over_description():
    out = _format_user_brief(
        _persona(brief_content="Long-form brief prose.", description="Short pitch.")
    )
    assert out.startswith("Long-form brief prose.")
    assert "Short pitch." not in out


def test_empty_brief_content_falls_back_to_description():
    out = _format_user_brief(
        _persona(brief_content="   ", description="Short pitch.")
    )
    assert out.startswith("Short pitch.")


def test_redact_brief_drops_brief_content_keeps_description():
    out = _format_user_brief(
        _persona(brief_content="Secret brief.", description="Short pitch."),
        redact_brief=True,
    )
    assert "Secret brief." not in out
    assert "Short pitch." in out


def test_redact_profile_strips_profile_fields():
    out = _format_user_brief(
        _persona(brief_content="Prose."), redact_profile=True
    )
    assert "Prose." in out
    assert "Founder" not in out
    assert "Acme" not in out
    assert "SF" not in out


def test_empty_everything_placeholder():
    out = _format_user_brief(
        _persona(brief_content="", description="", profile={})
    )
    assert out == "(no profile details set yet)"
