"""
Tests for `api.telegram`'s slash-command dispatcher and individual
handlers.

Strategy:
  - Replace `send_telegram_message` with a recorder so we capture the
    rendered text instead of making HTTP calls.
  - Stub each handler's underlying tool / DB read (search_zynd_personas,
    list_pending_meetings, list_events, brief tools, supabase client).
  - Assert the recorded message contains the right pieces.

The aim is to lock down the handler contract (what gets rendered, what
slash command base-name is dispatched, how `@botname` group form is
parsed) without coupling the test to exact wording — substrings only.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

# ── Tiny helpers ──────────────────────────────────────────────────────


class _Recorder:
    """Drop-in replacement for `send_telegram_message`. Records every
    call as (chat_id, text, parse_mode) so a single test can fire multiple
    sends and assert against them."""

    def __init__(self):
        self.calls: list[tuple[int, str, str | None]] = []

    async def __call__(self, chat_id, text, parse_mode="Markdown", **kwargs):
        self.calls.append((chat_id, text, parse_mode))
        return True

    @property
    def last_text(self) -> str:
        return self.calls[-1][1] if self.calls else ""

    def texts(self) -> list[str]:
        return [c[1] for c in self.calls]


@pytest.fixture
def recorder(monkeypatch):
    """Stub api.telegram.send_telegram_message with a Recorder."""
    from api import telegram as tg

    rec = _Recorder()
    monkeypatch.setattr(tg, "send_telegram_message", rec)
    return rec


# ── _parse_slash + dispatcher routing ─────────────────────────────────


def test_parse_slash_basic():
    from api.telegram import _parse_slash

    assert _parse_slash("/help") == ("help", "")
    assert _parse_slash("/todo buy milk") == ("todo", "buy milk")
    assert _parse_slash("/brief_add hello world") == ("brief_add", "hello world")


def test_parse_slash_handles_at_bot_suffix():
    """Group chats append @<botname> to commands. The dispatcher must
    look at the base name only."""
    from api.telegram import _parse_slash

    assert _parse_slash("/help@zynd_brief_bot") == ("help", "")
    assert _parse_slash("/todo@zynd_brief_bot buy milk") == ("todo", "buy milk")
    assert _parse_slash("/Calendar@Zynd_Brief_Bot week") == ("calendar", "week")


def test_parse_slash_returns_none_for_non_slash():
    from api.telegram import _parse_slash

    assert _parse_slash("hello") is None
    assert _parse_slash("") is None


def test_truncate_list_caps_with_footer():
    from api.telegram import _truncate_list

    rows = [f"• row {i}" for i in range(25)]
    out = _truncate_list(rows, cap=10)
    assert len(out) == 11
    assert out[-1].startswith("…and 15 more")


def test_escape_md_handles_underscores():
    from api.telegram import _escape_md

    assert _escape_md("John_Doe") == "John\\_Doe"
    assert _escape_md("a*b`c[d]e") == "a\\*b\\`c\\[d\\]e"


# ── Unknown command → friendly hint ───────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_command_shows_help_hint(recorder, monkeypatch):
    """Dispatching an unknown slash command should fall through to a
    friendly hint pointing at /help, NOT route to the LLM."""
    from api import telegram as tg

    # `process_telegram_message` looks up the user via telegram_store —
    # stub it to return a real user_id so we get past the auth check.
    monkeypatch.setattr(tg.telegram_store, "get_user_id_for_chat", lambda cid: "user_1")

    await tg.process_telegram_message(123, "/nonsense")
    assert recorder.calls, "expected at least one Telegram send"
    text = recorder.last_text
    assert "/nonsense" in text or "nonsense" in text
    assert "/help" in text.lower()


# ── /help and /reset ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_help_lists_all_commands(recorder):
    from api.telegram import _handle_help

    await _handle_help("user_1", 123, "")
    text = recorder.last_text
    for cmd in [
        "/brief",
        "/brief\\_add",
        "/meetings",
        "/calendar",
        "/inbox",
        "/who",
        "/connect",
        "/connections",
        "/todos",
        "/todo",
        "/reset",
        "/help",
    ]:
        assert cmd in text, f"help text is missing {cmd!r}"


@pytest.mark.asyncio
async def test_reset_clears_history(recorder, monkeypatch):
    from api import telegram as tg

    cleared: list[str] = []
    monkeypatch.setattr(tg.telegram_store, "clear_history", lambda cid: cleared.append(cid))
    monkeypatch.setattr(tg, "_conversations", {}, raising=False)

    await tg._handle_reset("user_1", 123, "")
    assert cleared == ["tg_123"]
    assert "forgotten" in recorder.last_text.lower() or "fresh start" in recorder.last_text.lower()


# ── /meetings ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meetings_renders_pending(recorder, monkeypatch):
    """list_pending_meetings returns two rows split by who must act
    next — we should render both with the right marker."""
    from api import telegram as tg

    fake_scheduling = types.ModuleType("mcp.tools.scheduling")

    def list_pending_meetings(user_id):
        return {
            "status": "success",
            "awaiting_me_count": 1,
            "awaiting_them_count": 1,
            "awaiting_me": [
                {
                    "id": "task_1",
                    "payload": {"title": "Intro call", "start_time": "2026-05-21T15:00:00Z"},
                    "initiator_user_id": "other_user",
                    "recipient_user_id": "user_1",
                    "initiator_name": "Sarah",
                    "recipient_name": "Me",
                }
            ],
            "awaiting_them": [
                {
                    "id": "task_2",
                    "payload": {"title": "Coffee", "start_time": "2026-05-23T10:00:00Z"},
                    "initiator_user_id": "user_1",
                    "recipient_user_id": "other_user",
                    "initiator_name": "Me",
                    "recipient_name": "Sarah",
                }
            ],
        }

    fake_scheduling.list_pending_meetings = list_pending_meetings
    monkeypatch.setitem(sys.modules, "mcp.tools.scheduling", fake_scheduling)

    await tg._handle_meetings("user_1", 123, "")
    text = recorder.last_text
    assert "Intro call" in text
    assert "Coffee" in text
    assert "Sarah" in text


@pytest.mark.asyncio
async def test_meetings_empty_state(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.scheduling")
    fake.list_pending_meetings = lambda user_id: {
        "awaiting_me": [], "awaiting_them": [], "awaiting_me_count": 0, "awaiting_them_count": 0,
    }
    monkeypatch.setitem(sys.modules, "mcp.tools.scheduling", fake)

    await tg._handle_meetings("user_1", 123, "")
    assert "no pending meetings" in recorder.last_text.lower()


# ── /calendar ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_today_filters_by_date(recorder, monkeypatch):
    from api import telegram as tg
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    far_future = "2099-01-01"

    fake = types.ModuleType("mcp.tools.google.calendar")
    fake.list_events = lambda user_id, max_results=10: {
        "success": True,
        "events": [
            {"id": "e1", "summary": "Standup", "start": f"{today}T09:00:00Z", "end": f"{today}T09:30:00Z"},
            {"id": "e2", "summary": "Far future", "start": f"{far_future}T09:00:00Z", "end": f"{far_future}T10:00:00Z"},
        ],
    }
    fake_pkg = types.ModuleType("mcp.tools.google")
    monkeypatch.setitem(sys.modules, "mcp.tools.google", fake_pkg)
    monkeypatch.setitem(sys.modules, "mcp.tools.google.calendar", fake)

    await tg._handle_calendar("user_1", 123, "today")
    text = recorder.last_text
    assert "Standup" in text
    assert "Far future" not in text


@pytest.mark.asyncio
async def test_calendar_empty_state(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.google.calendar")
    fake.list_events = lambda user_id, max_results=10: {"success": True, "events": []}
    fake_pkg = types.ModuleType("mcp.tools.google")
    monkeypatch.setitem(sys.modules, "mcp.tools.google", fake_pkg)
    monkeypatch.setitem(sys.modules, "mcp.tools.google.calendar", fake)

    await tg._handle_calendar("user_1", 123, "today")
    assert "nothing on your calendar today" in recorder.last_text.lower()


@pytest.mark.asyncio
async def test_calendar_rejects_unknown_scope(recorder):
    from api.telegram import _handle_calendar

    await _handle_calendar("user_1", 123, "tomorrow")
    assert "today" in recorder.last_text.lower()
    assert "week" in recorder.last_text.lower()


# ── /inbox ────────────────────────────────────────────────────────────


class _StubSB:
    """Minimal Supabase client stub. Returns canned responses per
    (table, op) so each test sets up exactly the read it cares about."""

    def __init__(self, responses):
        self._responses = responses
        self._table = None
        self._filters: list[tuple[str, str]] = []
        self._select = ""
        self._order = []
        self._limit = None

    def table(self, name):
        self._table = name
        self._filters = []
        self._select = ""
        self._order = []
        self._limit = None
        return self

    def select(self, cols):
        self._select = cols
        return self

    def insert(self, payload):
        self._payload = payload
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def delete(self):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, *a, **kw):
        self._order.append((a, kw))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def in_(self, *a, **kw):
        return self

    def execute(self):
        # Look up a response by (table, dict-of-filters).
        key = (self._table, tuple(self._filters))
        if key in self._responses:
            data = self._responses[key]
            return types.SimpleNamespace(data=data)
        # Generic match by table-only fallback.
        if self._table in self._responses:
            return types.SimpleNamespace(data=self._responses[self._table])
        return types.SimpleNamespace(data=[])


@pytest.mark.asyncio
async def test_inbox_empty_when_no_persona(recorder, monkeypatch):
    from api import telegram as tg

    fake_pm = types.ModuleType("agent.persona_manager")
    fake_pm.get_persona_status = lambda user_id: {"deployed": False}
    if "agent" not in sys.modules:
        monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.persona_manager", fake_pm)

    await tg._handle_inbox("user_1", 123, "")
    assert "📭" in recorder.last_text or "persona" in recorder.last_text.lower()


@pytest.mark.asyncio
async def test_inbox_lists_awaiting_threads(recorder, monkeypatch):
    from api import telegram as tg

    fake_pm = types.ModuleType("agent.persona_manager")
    fake_pm.get_persona_status = lambda user_id: {"deployed": True, "agent_id": "agent_me"}
    if "agent" not in sys.modules:
        monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.persona_manager", fake_pm)

    threads = [
        {
            "id": "thread_1",
            "initiator_id": "agent_other",
            "receiver_id": "agent_me",
            "initiator_name": "Sarah",
            "receiver_name": "Me",
        }
    ]
    msgs = [
        {
            "sender_id": "agent_other",
            "content": "Hey, can we meet tomorrow at 3pm?",
            "created_at": "2026-05-20T10:00:00Z",
        }
    ]
    responses = {
        ("dm_threads", (("initiator_id", "agent_me"),)): [],
        ("dm_threads", (("receiver_id", "agent_me"),)): threads,
        ("dm_messages", (("thread_id", "thread_1"),)): msgs,
    }
    stub = _StubSB(responses)
    monkeypatch.setattr(tg.config, "get_supabase", lambda: stub)

    await tg._handle_inbox("user_1", 123, "")
    text = recorder.last_text
    assert "Sarah" in text
    assert "Hey" in text or "meet tomorrow" in text


# ── /who ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_who_lists_top_matches(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.zynd_network")
    fake.search_zynd_personas = lambda query, top_k=5: {
        "status": "success",
        "results": [
            {
                "name": "Alice Chen",
                "agent_id": "agent_alice",
                "agent_handle": "alice",
                "description": "Founder at Acme",
            },
            {
                "name": "Alex Pearson",
                "agent_id": "agent_alex",
                "agent_handle": "alex",
                "description": "PM at Globex",
            },
        ],
    }
    monkeypatch.setitem(sys.modules, "mcp.tools.zynd_network", fake)

    await tg._handle_who("user_1", 123, "Al")
    text = recorder.last_text
    assert "Alice Chen" in text
    assert "Alex Pearson" in text
    assert "alice" in text  # handle present
    assert "t.me/alice" in text


@pytest.mark.asyncio
async def test_who_requires_arg(recorder):
    from api.telegram import _handle_who

    await _handle_who("user_1", 123, "")
    assert "/who" in recorder.last_text


@pytest.mark.asyncio
async def test_who_no_matches(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.zynd_network")
    fake.search_zynd_personas = lambda query, top_k=5: {"status": "success", "results": []}
    monkeypatch.setitem(sys.modules, "mcp.tools.zynd_network", fake)

    await tg._handle_who("user_1", 123, "Nobody")
    assert "No personas found" in recorder.last_text


# ── /connect ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_sends_request(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.zynd_network")
    fake.search_zynd_personas = lambda query, top_k=5: {
        "results": [
            {"name": "Sarah Lin", "agent_id": "agent_sarah", "agent_handle": "sarahlin"}
        ]
    }

    def request_connection(user_id, target_agent_id, target_name="Network Agent"):
        return {"status": "success", "thread_id": "thread_new", "target_name": target_name}

    fake.request_connection = request_connection
    monkeypatch.setitem(sys.modules, "mcp.tools.zynd_network", fake)

    await tg._handle_connect("user_1", 123, "sarahlin")
    assert "Sarah Lin" in recorder.last_text
    assert "request sent" in recorder.last_text.lower() or "🔗" in recorder.last_text


@pytest.mark.asyncio
async def test_connect_already_exists(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.zynd_network")
    fake.search_zynd_personas = lambda query, top_k=5: {
        "results": [
            {"name": "Sarah", "agent_id": "agent_sarah", "agent_handle": "sarah"}
        ]
    }
    fake.request_connection = lambda **kw: {
        "status": "already_exists",
        "connection_status": "pending",
    }
    monkeypatch.setitem(sys.modules, "mcp.tools.zynd_network", fake)

    await tg._handle_connect("user_1", 123, "sarah")
    assert "pending" in recorder.last_text.lower()


# ── /connections ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connections_groups_by_status(recorder, monkeypatch):
    from api import telegram as tg

    fake = types.ModuleType("mcp.tools.zynd_network")
    fake.list_my_connections = lambda user_id: {
        "my_agent_id": "agent_me",
        "connections": [
            {"partner_name": "Sarah", "partner_agent_id": "agent_sarah", "initiated_by_me": True},
        ],
        "pending_requests": [
            {"partner_name": "Bob", "partner_agent_id": "agent_bob", "initiated_by_me": False},
            {"partner_name": "Carol", "partner_agent_id": "agent_carol", "initiated_by_me": True},
        ],
    }
    monkeypatch.setitem(sys.modules, "mcp.tools.zynd_network", fake)

    await tg._handle_connections("user_1", 123, "")
    text = recorder.last_text
    assert "Connected" in text
    assert "Sarah" in text
    assert "Incoming" in text
    assert "Bob" in text  # incoming
    assert "Carol" in text  # outgoing


# ── /todos and /todo ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_todos_lists_open(recorder, monkeypatch):
    from api import telegram as tg

    stub = _StubSB({
        "brief_todos": [
            {"id": "11111111-2222-3333-4444-555555556789", "title": "Reply to Sarah"},
            {"id": "aabbccdd-eeff-0011-2233-445566778899", "title": "Book flight"},
        ],
    })
    monkeypatch.setattr(tg.config, "get_supabase", lambda: stub)

    await tg._handle_todos("user_1", 123, "")
    text = recorder.last_text
    assert "Reply to Sarah" in text
    assert "Book flight" in text
    assert "6789" in text  # last 4 of id 1
    assert "8899" in text  # last 4 of id 2


@pytest.mark.asyncio
async def test_todos_empty(recorder, monkeypatch):
    from api import telegram as tg

    stub = _StubSB({"brief_todos": []})
    monkeypatch.setattr(tg.config, "get_supabase", lambda: stub)

    await tg._handle_todos("user_1", 123, "")
    assert "no open todos" in recorder.last_text.lower()


@pytest.mark.asyncio
async def test_todo_add_inserts(recorder, monkeypatch):
    from api import telegram as tg

    inserted: list[dict] = []

    class _InsertSB(_StubSB):
        def execute(self):
            if self._table == "brief_todos" and getattr(self, "_payload", None):
                inserted.append(self._payload)
                return types.SimpleNamespace(data=[self._payload])
            return super().execute()

    monkeypatch.setattr(tg.config, "get_supabase", lambda: _InsertSB({}))

    await tg._handle_todo("user_1", 123, "buy milk")
    assert inserted, "expected an insert into brief_todos"
    assert inserted[0]["title"] == "buy milk"
    assert inserted[0]["user_id"] == "user_1"
    assert inserted[0]["done"] is False
    assert "✅" in recorder.last_text or "added" in recorder.last_text.lower()


@pytest.mark.asyncio
async def test_todo_add_keyword_shorthand(recorder, monkeypatch):
    """`/todo add foo` should be equivalent to `/todo foo`."""
    from api import telegram as tg

    inserted: list[dict] = []

    class _InsertSB(_StubSB):
        def execute(self):
            if self._table == "brief_todos" and getattr(self, "_payload", None):
                inserted.append(self._payload)
                return types.SimpleNamespace(data=[self._payload])
            return super().execute()

    monkeypatch.setattr(tg.config, "get_supabase", lambda: _InsertSB({}))

    await tg._handle_todo("user_1", 123, "add finish the report")
    assert inserted[0]["title"] == "finish the report"


@pytest.mark.asyncio
async def test_todo_empty_arg_rejected(recorder):
    from api.telegram import _handle_todo

    await _handle_todo("user_1", 123, "")
    assert "/todo" in recorder.last_text


# ── Dispatcher routes correctly for @bot group form ───────────────────


@pytest.mark.asyncio
async def test_dispatcher_routes_at_bot_form(recorder, monkeypatch):
    """`/help@zynd_brief_bot` should reach the /help handler."""
    from api import telegram as tg

    monkeypatch.setattr(tg.telegram_store, "get_user_id_for_chat", lambda cid: "user_1")

    await tg.process_telegram_message(123, "/help@zynd_brief_bot")
    # The help handler sends the full HELP_TEXT — check for a distinctive piece.
    text = recorder.last_text
    assert "Zynd Persona" in text
    assert "/brief" in text
