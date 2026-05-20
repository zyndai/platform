"""
Tests for the Brief MCP tools and the `_ensure_brief_doc` helper.

We stub `agent.persona_manager` and `mcp.tools.google.docs` so these
tests never hit Google or Supabase. The tools are thin wrappers, so the
test surface is mostly: did we propagate the right structured codes
(`no_persona`, `google_unavailable`) and the right success payload.
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_stub_persona_manager(monkeypatch, *, brief_state, init_outcome="ok", persona_status=None):
    """Replace `agent.persona_manager` in sys.modules with a stub.

    Args:
      brief_state: dict returned by get_brief() — must include {"exists": bool}.
      init_outcome: "ok" → init returns a doc id; "no_persona" raises
        ValueError("No active persona ..."); "google_fail" raises a generic
        Exception (simulates missing OAuth scope / Drive API error).
      persona_status: dict returned by get_persona_status(). If None, defaults
        to a deployed persona with a brief_doc_id when the brief exists.
    """
    stub = types.ModuleType("agent.persona_manager")

    if persona_status is None:
        persona_status = {
            "deployed": True,
            "brief_doc_id": "doc_xyz" if brief_state.get("exists") else None,
            "brief_doc_url": "https://docs.google.com/document/d/doc_xyz/edit",
            "name": "Test User",
        }

    # Mutable state object so init can flip exists/doc_id like the real
    # code does (a successful init writes brief_doc_id onto the persona row).
    state = {
        "brief_state": dict(brief_state),
        "persona_status": dict(persona_status),
    }

    def get_brief(user_id: str):
        if state["brief_state"].get("raises") == "no_persona":
            raise ValueError("No active persona.")
        return state["brief_state"]

    def init_brief_doc(user_id: str):
        if init_outcome == "no_persona":
            raise ValueError("No active persona — create a persona before initializing a brief.")
        if init_outcome == "google_fail":
            raise Exception("HttpError 401: drive.file scope missing")
        # Successful init: mirror the real side-effect of writing the
        # doc id onto the persona row.
        state["brief_state"] = {
            "exists": True,
            "doc_id": "doc_xyz",
            "url": state["persona_status"]["brief_doc_url"],
            "content": "",
        }
        state["persona_status"]["brief_doc_id"] = "doc_xyz"
        return {"doc_id": "doc_xyz", "url": state["persona_status"]["brief_doc_url"], "created": True}

    def get_persona_status(user_id: str):
        return state["persona_status"]

    def save_brief_content(user_id: str, content: str):
        return {"success": True, "doc_id": persona_status.get("brief_doc_id") or "doc_xyz"}

    stub.get_brief = get_brief
    stub.init_brief_doc = init_brief_doc
    stub.get_persona_status = get_persona_status
    stub.save_brief_content = save_brief_content

    # Build a parent `agent` package stub too if needed, using monkeypatch
    # so it's torn down between tests (avoids polluting `agent` import
    # state for the rest of the suite).
    if "agent" not in sys.modules:
        monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.persona_manager", stub)
    # If `agent` is the real package (already imported by a prior test),
    # `from agent import persona_manager` reads the cached attribute on
    # the package object, NOT sys.modules. Patch the attribute so the
    # stub actually takes effect.
    agent_pkg = sys.modules["agent"]
    monkeypatch.setattr(agent_pkg, "persona_manager", stub, raising=False)
    return stub


def _install_stub_docs(monkeypatch, *, append_ok=True):
    """Stub `mcp.tools.google.docs.append_to_document`."""
    fake = types.ModuleType("mcp.tools.google.docs")

    def append_to_document(user_id: str, document_id: str, text: str):
        if append_ok:
            return {"success": True, "document_id": document_id}
        return {"success": False, "error": "google error"}

    def read_document(user_id: str, document_id: str):
        return {"success": True, "content": "hello", "title": "Brief"}

    def replace_document_body(user_id: str, document_id: str, text: str):
        return {"success": True, "document_id": document_id}

    def create_document(user_id: str, title: str):
        return {"success": True, "document_id": "doc_xyz", "link": "https://docs.google.com/doc_xyz"}

    fake.append_to_document = append_to_document
    fake.read_document = read_document
    fake.replace_document_body = replace_document_body
    fake.create_document = create_document
    monkeypatch.setitem(sys.modules, "mcp.tools.google.docs", fake)


def _reload_brief_module():
    """Drop a cached `mcp.tools.brief` import so the lazy-import lookups
    inside the tool functions see the stubs we just installed."""
    sys.modules.pop("mcp.tools.brief", None)
    import importlib

    import mcp.tools.brief as brief

    importlib.reload(brief)
    return brief


# ── _ensure_brief_doc ─────────────────────────────────────────────────


def test_ensure_brief_doc_existing(monkeypatch):
    _install_stub_persona_manager(monkeypatch, brief_state={"exists": True})
    brief = _reload_brief_module()

    result = brief._ensure_brief_doc("user_1")
    assert result == {"ok": True}


def test_ensure_brief_doc_init_success(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"exists": False, "fallback_description": ""},
        init_outcome="ok",
    )
    brief = _reload_brief_module()

    result = brief._ensure_brief_doc("user_1")
    assert result["ok"] is True
    assert result.get("created") is True


def test_ensure_brief_doc_no_persona(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"raises": "no_persona"},
        init_outcome="no_persona",
    )
    brief = _reload_brief_module()

    result = brief._ensure_brief_doc("user_1")
    assert result["ok"] is False
    assert result["code"] == "no_persona"
    assert "dashboard" in result["message"].lower()


def test_ensure_brief_doc_google_unavailable(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"exists": False, "fallback_description": ""},
        init_outcome="google_fail",
    )
    brief = _reload_brief_module()

    result = brief._ensure_brief_doc("user_1")
    assert result["ok"] is False
    assert result["code"] == "google_unavailable"
    assert "Google" in result["message"] or "google" in result["message"]


# ── read_my_brief ─────────────────────────────────────────────────────


def test_read_my_brief_no_brief(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"exists": False, "fallback_description": "fallback"},
    )
    brief = _reload_brief_module()

    result = brief.read_my_brief("user_1")
    assert result["success"] is True
    assert result["exists"] is False
    # read should not auto-init
    assert "message" in result


def test_read_my_brief_happy_path(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={
            "exists": True,
            "doc_id": "doc_xyz",
            "url": "https://docs.google.com/document/d/doc_xyz/edit",
            "content": "I prefer afternoons.",
        },
    )
    brief = _reload_brief_module()

    result = brief.read_my_brief("user_1")
    assert result["success"] is True
    assert result["exists"] is True
    assert result["content"] == "I prefer afternoons."
    assert "doc_xyz" in result["url"]


# ── append_to_my_brief ────────────────────────────────────────────────


def test_append_creates_doc_on_first_call(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"exists": False, "fallback_description": ""},
        init_outcome="ok",
    )
    _install_stub_docs(monkeypatch, append_ok=True)
    brief = _reload_brief_module()

    result = brief.append_to_my_brief("user_1", "I love async patterns.")
    assert result["success"] is True
    assert result["appended"] == "I love async patterns."


def test_append_empty_text_is_rejected(monkeypatch):
    _install_stub_persona_manager(monkeypatch, brief_state={"exists": True})
    _install_stub_docs(monkeypatch)
    brief = _reload_brief_module()

    result = brief.append_to_my_brief("user_1", "   ")
    assert result["success"] is False


def test_append_propagates_no_persona(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"raises": "no_persona"},
        init_outcome="no_persona",
    )
    _install_stub_docs(monkeypatch)
    brief = _reload_brief_module()

    result = brief.append_to_my_brief("user_1", "hello")
    assert result["success"] is False
    assert result["code"] == "no_persona"


def test_append_propagates_google_unavailable(monkeypatch):
    _install_stub_persona_manager(
        monkeypatch,
        brief_state={"exists": False, "fallback_description": ""},
        init_outcome="google_fail",
    )
    _install_stub_docs(monkeypatch)
    brief = _reload_brief_module()

    result = brief.append_to_my_brief("user_1", "hello")
    assert result["success"] is False
    assert result["code"] == "google_unavailable"


# ── replace_my_brief / clear_my_brief ─────────────────────────────────


def test_replace_my_brief_happy_path(monkeypatch):
    _install_stub_persona_manager(monkeypatch, brief_state={"exists": True})
    _install_stub_docs(monkeypatch)
    brief = _reload_brief_module()

    result = brief.replace_my_brief("user_1", "Brand new brief.")
    assert result["success"] is True
    assert result["content"] == "Brand new brief."


def test_clear_my_brief_happy_path(monkeypatch):
    _install_stub_persona_manager(monkeypatch, brief_state={"exists": True})
    _install_stub_docs(monkeypatch)
    brief = _reload_brief_module()

    result = brief.clear_my_brief("user_1")
    assert result["success"] is True
    assert result["content"] == ""


# ── add_todo ─────────────────────────────────────────────────────────


class _CapturingSB:
    """Lightweight Supabase stub that captures the last `insert` payload
    so a test can assert what we tried to write."""

    def __init__(self):
        self.last_insert: dict | None = None

    def table(self, _name):
        return self

    def insert(self, payload):
        self.last_insert = payload
        return self

    def execute(self):
        return types.SimpleNamespace(data=[{"id": "todo_abc", **(self.last_insert or {})}])


def test_add_todo_inserts_row(monkeypatch):
    brief = _reload_brief_module()
    import config

    stub = _CapturingSB()
    monkeypatch.setattr(config, "get_supabase", lambda: stub)

    result = brief.add_todo("user_1", "Email Sarah about the demo")
    assert result["success"] is True
    assert result["title"] == "Email Sarah about the demo"
    assert result["todo_id"] == "todo_abc"
    # The agent never sets done=True itself — that's the user's job.
    assert stub.last_insert["done"] is False
    assert stub.last_insert["user_id"] == "user_1"


def test_add_todo_rejects_empty_title(monkeypatch):
    brief = _reload_brief_module()
    result = brief.add_todo("user_1", "   ")
    assert result["success"] is False


def test_add_todo_truncates_overly_long_title(monkeypatch):
    brief = _reload_brief_module()
    import config

    stub = _CapturingSB()
    monkeypatch.setattr(config, "get_supabase", lambda: stub)

    long_title = "x" * 500
    result = brief.add_todo("user_1", long_title)
    assert result["success"] is True
    assert len(result["title"]) <= 200
