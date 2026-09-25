"""
Tests for the user-facing error helper.

The goal is to make sure raw exceptions are never surfaced verbatim to the
user; instead errors carry a non-technical what/why/hint shape.
"""

from __future__ import annotations

import pytest

from mcp.tools.error_utils import friendly_error, friendly_error_message


def test_friendly_error_never_leaks_raw_exception():
    e = Exception("http://internal-api.zynd.ai/deployments blew up: stack trace line 42")
    out = friendly_error("post to X", e)

    raw = str(e)
    assert raw not in out["error"]
    assert raw not in out["error_message"]
    assert "http" not in out["error"].lower()
    assert "stack trace" not in out["error_message"].lower()


def test_friendly_error_returns_three_parts():
    out = friendly_error("read your calendar", Exception("timeout"))

    assert out["success"] is False
    assert out["error"]
    assert out["error_message"]
    assert out["hint"]


def test_classifier_timeout():
    out = friendly_error("call the service", Exception("ReadTimeout waiting for response"))

    assert "didn't respond in time" in out["error"].lower()
    assert "timed out" in out["error_message"].lower()
    assert "try again" in out["hint"].lower()


def test_classifier_not_connected():
    out = friendly_error("post to X", Exception("X not connected. Please connect your account first."))

    assert "isn't connected" in out["error"].lower()
    assert out["hint"].lower().startswith("connect")


def test_classifier_credentials():
    out = friendly_error("post to LinkedIn", Exception("HttpError 401: unauthorized"))

    assert "connection expired" in out["error"].lower() or "expired" in out["error"].lower()
    assert "reconnect" in out["hint"].lower()


def test_classifier_rate_limit():
    out = friendly_error("talk to Notion", Exception("Rate limited (429)"))

    assert "busy" in out["error"].lower()
    assert "wait" in out["hint"].lower()


def test_classifier_default_technical_problem():
    out = friendly_error("do the thing", Exception("kaboom"))

    assert "technical problem" in out["error_message"].lower() or "couldn't" in out["error"].lower()
    assert "try again" in out["hint"].lower()


def test_explicit_hint_overrides_classifier():
    out = friendly_error("post to X", Exception("timeout"), hint="Custom next step.")

    assert out["hint"] == "Custom next step."


def test_friendly_error_message_uses_same_classifier():
    out = friendly_error_message("search the network", "Registry timed out.")

    assert out["success"] is False
    assert "didn't respond" in out["error_message"].lower() or "timed out" in out["error_message"].lower()
    assert out["hint"]


def test_title_falls_back_when_operation_is_not_a_verb_phrase():
    out = friendly_error("this service", Exception("something failed"))

    assert out["error"] == "Something went wrong"
