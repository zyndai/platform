"""Consolidated MCP context packet and mutually exclusive write modes."""
import threading
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.server.auth import AccessToken

import app.mcp_http as m
from app.config import settings


def token(scopes, uid="alice"):
    return AccessToken(token="test", client_id=uid, subject=uid, scopes=scopes)


@pytest.fixture
def packet(monkeypatch):
    pool = AsyncMock()
    pool.fetchrow.return_value = {
        "display_name": " Alice ", "email": "alice@example.com",
        "supabase_user_id": "suid-alice",
        "socials": {"linkedin": "stored-linkedin", "github": "stored-github", "twitter": "stored-x"},
    }
    mocks = {
        "pool": pool,
        "persona": AsyncMock(return_value={
            "name": "Persona Alice", "description": "Founder", "capabilities": ["Rust"],
            "profile": {
                "title": "Engineer", "organization": "Acme", "location": "Paris",
                "interests": ["compilers"], "linkedin": "persona-linkedin",
                "github": "  ", "twitter": "persona-x",
            },
        }),
        "brief": AsyncMock(return_value={"success": True, "content": "Building Acme"}),
        "facts": AsyncMock(return_value=[{"predicate": "has_skill", "object": "Rust"}]),
        "slice": AsyncMock(return_value=[{"predicate": "is_building", "object": "Acme"}]),
        "card": AsyncMock(return_value=[{"predicate": "has_skill", "object": "Python"}]),
        "owner": AsyncMock(return_value={"ok": True, "data": {"pending": 2, "activity": {"views": 3}}}),
    }
    monkeypatch.setattr(m, "_get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("app.services.self_context.persona.get_status", mocks["persona"])
    monkeypatch.setattr(m.brief_tools, "read_my_brief", mocks["brief"])
    monkeypatch.setattr(m, "active_context", mocks["facts"])
    monkeypatch.setattr(m, "context_slice", mocks["slice"])
    monkeypatch.setattr(m, "get_card", mocks["card"])
    monkeypatch.setattr("app.tools.card_status.get_owner_status", mocks["owner"])
    return mocks


@pytest.mark.parametrize("scopes,allowed", [
    (["memory:write"], False),
    (["memory:write", "cards:read"], True),
    (["memory:write", "cards:approve"], False),
    (["user"], True),
])
async def test_packet_owner_sections_use_actual_token_scopes(packet, scopes, allowed):
    result = await m.get_my_context(uid="alice", token=token(scopes))
    if allowed:
        assert result["status"] == {"pending": 2, "activity": {"views": 3}}
        assert result["activity"] == {"views": 3}
        packet["owner"].assert_awaited_once_with(packet["pool"], "alice")
    else:
        assert "status" not in result and "activity" not in result
        packet["owner"].assert_not_awaited()


async def test_packet_normalizes_nested_profile_socials_and_linked_brief(packet):
    result = await m.get_my_context(uid="alice", token=token(["memory:write"]))
    assert result["identity"] == {"name": "Alice", "email": "alice@example.com"}
    assert result["profile"] == {
        "name": "Persona Alice", "description": "Founder", "capabilities": ["Rust"],
        "title": "Engineer", "organization": "Acme", "location": "Paris",
        "interests": ["compilers"], "socials": {
            "linkedin": "persona-linkedin", "github": "", "x": "persona-x",
            "instagram": "", "website": "",
        },
    }
    assert result["socials"]["linkedin"] == "persona-linkedin"
    assert result["socials"]["github"] == "stored-github"
    assert result["socials"]["x"] == "persona-x"
    assert "twitter" not in result["socials"]
    assert result["brief"] == "Building Acme"
    assert set(result["present"]) == {"identity", "profile", "socials", "brief", "facts", "card"}
    packet["pool"].fetchrow.assert_awaited_once()
    packet["persona"].assert_awaited_once_with("suid-alice")
    packet["brief"].assert_awaited_once_with("suid-alice")


async def test_synchronous_brief_backend_runs_off_event_loop_thread(packet):
    loop_thread = threading.get_ident()
    read_threads = []

    async def read_brief(suid):
        read_threads.append(threading.get_ident())
        return {"success": True, "content": "Building Acme"}

    packet["brief"].side_effect = read_brief
    result = await m.get_my_context(uid="alice", token=token(["memory:write"]))
    assert result["brief"] == "Building Acme"
    assert len(read_threads) == 1
    assert read_threads[0] != loop_thread


@pytest.mark.parametrize("topic,k,expected_k", [(" Rust ", 99, 50), ("Rust", 0, 1), ("  ", 20, 20), (None, 20, 20)])
async def test_topic_filters_facts_only_and_k_is_bounded(packet, topic, k, expected_k):
    result = await m.get_my_context(topic=topic, k=k, uid="alice", token=token(["memory:write"]))
    if topic and topic.strip():
        packet["slice"].assert_awaited_once_with(packet["pool"], "alice", topic.strip(), expected_k)
        packet["facts"].assert_not_awaited()
        assert result["facts"] == packet["slice"].return_value
    else:
        packet["facts"].assert_awaited_once_with(packet["pool"], "alice", expected_k)
        packet["slice"].assert_not_awaited()
    assert result["identity"]["name"] == "Alice"
    assert result["card"] == packet["card"].return_value
    assert result["brief"] == "Building Acme"


@pytest.mark.parametrize("owner_result", [{"ok": False, "error": "disabled"}, {"ok": False, "error": "timeout"}])
async def test_authorized_owner_unavailable_is_null_not_empty(packet, owner_result):
    packet["owner"].return_value = owner_result
    result = await m.get_my_context(uid="alice", token=token(["cards:read"]))
    assert result["status"] is None and result["activity"] is None
    assert "status" not in result["present"] and "activity" not in result["present"]
    assert result["facts"]


async def test_owner_exception_keeps_packet_available_with_explicit_nulls(packet):
    packet["owner"].side_effect = RuntimeError("owner service down")
    result = await m.get_my_context(uid="alice", token=token(["user"]))
    assert result["status"] is None and result["activity"] is None
    assert result["identity"]["name"] == "Alice"
    assert result["facts"] and result["card"]
    packet["owner"].assert_awaited_once()


async def test_optional_failures_preserve_local_context_and_fallback_socials(packet):
    packet["persona"].side_effect = RuntimeError("persona down")
    packet["brief"].side_effect = RuntimeError("brief down")
    result = await m.get_my_context(uid="alice", token=token(["memory:write"]))
    assert result["profile"] is None and result["brief"] is None
    assert result["identity"]["name"] == "Alice"
    assert result["socials"]["x"] == "stored-x"
    assert result["facts"] and result["card"]
    assert "profile" not in result["present"] and "brief" not in result["present"]


async def test_identity_only_packet_does_not_claim_whitespace_or_empty_sections(packet):
    packet["pool"].fetchrow.return_value = {
        "display_name": "Alice", "email": None, "supabase_user_id": None,
        "socials": {"github": "  ", "twitter": "\n"},
    }
    packet["facts"].return_value = []
    packet["card"].return_value = []
    packet["brief"].return_value = {"success": True, "content": "  "}
    result = await m.get_my_context(uid="alice", token=token(["memory:write"]))
    assert set(result) == {"identity", "profile", "socials", "brief", "facts", "card", "present"}
    assert result["present"] == ["identity"]
    assert result["facts"] == result["card"] == []
    assert result["profile"] is None
    packet["persona"].assert_not_awaited()
    packet["brief"].assert_awaited_once_with("alice")


async def test_empty_persona_shape_is_not_substantive_profile_content(packet):
    packet["persona"].return_value = {
        "name": " ", "description": "\n", "capabilities": [],
        "profile": {"title": " ", "interests": [], "twitter": " "},
    }
    packet["pool"].fetchrow.return_value["socials"] = {}
    result = await m.get_my_context(uid="alice", token=token(["memory:write"]))
    assert "profile" not in result["present"]
    assert "socials" not in result["present"]


@pytest.mark.parametrize("section", ["facts", "card"])
async def test_local_database_failures_are_not_empty_success(packet, section):
    packet[section].side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await m.get_my_context(uid="alice", token=token(["memory:write"]))


async def test_missing_account_does_not_manufacture_identity_packet(packet):
    packet["pool"].fetchrow.return_value = None
    with pytest.raises(LookupError):
        await m.get_my_context(uid="missing", token=token(["memory:write"], "missing"))
    packet["persona"].assert_not_awaited()
    packet["owner"].assert_not_awaited()


async def test_every_packet_section_is_bound_to_current_caller(packet):
    async def row(query, uid):
        return {"display_name": uid, "email": f"{uid}@example.com",
                "supabase_user_id": f"suid-{uid}", "socials": {"github": f"stored-{uid}"}}

    packet["pool"].fetchrow.side_effect = row
    packet["persona"].side_effect = lambda suid: {"name": suid, "description": suid, "profile": {}}
    packet["brief"].side_effect = lambda suid: {"success": True, "content": suid}
    packet["facts"].side_effect = lambda pool, uid, k: [{"object": uid}]
    packet["card"].side_effect = lambda pool, uid: [{"object": uid}]
    packet["owner"].side_effect = lambda pool, uid: {"ok": True, "data": {"owner": uid, "activity": {"owner": uid}}}
    for uid in ("alice", "bob"):
        result = await m.get_my_context(uid=uid, token=token(["user"], uid))
        assert result["identity"] == {"name": uid, "email": f"{uid}@example.com"}
        assert result["profile"]["name"] == f"suid-{uid}"
        assert result["socials"]["github"] == f"stored-{uid}"
        assert result["brief"] == f"suid-{uid}"
        assert result["facts"] == result["card"] == [{"object": uid}]
        assert result["status"]["owner"] == result["activity"]["owner"] == uid


@pytest.mark.parametrize("field,value", [
    ("role", "Engineer"), ("notes", "Learning Rust"), ("goals", "Ship Acme"),
    ("skills", ["Rust"]), ("languages", ["Python"]), ("frameworks", ["React"]),
    ("tools", ["Docker"]), ("projects", ["Acme"]),
])
async def test_mixed_write_modes_rejected_before_any_side_effect(field, value):
    with patch.object(m, "_get_pool", AsyncMock()) as pool, \
         patch.object(m, "_get_arq", AsyncMock()) as arq, \
         patch.object(m, "ingest_turns", AsyncMock()) as ingest, \
         patch("app.services.findability.declare_for_review", AsyncMock()) as declare:
        result = await m.report_user_info(text="I am building Acme", uid="alice", **{field: value})
    assert result == {"saved": False, "reason": "Use text alone or typed fields, not both"}
    pool.assert_not_awaited()
    arq.assert_not_awaited()
    ingest.assert_not_awaited()
    declare.assert_not_awaited()


async def test_free_text_preserves_length_source_minimum_and_bypasses_typed_cap(monkeypatch):
    monkeypatch.setattr(settings, "feature_s05_typed_capture", True)
    text = "I build compilers. " * 400
    pool, arq = AsyncMock(), AsyncMock()
    with patch.object(m, "_get_pool", AsyncMock(return_value=pool)), \
         patch.object(m, "_get_arq", AsyncMock(return_value=arq)), \
         patch.object(m, "ingest_turns", AsyncMock(return_value=(1, 0))) as ingest, \
         patch("app.services.findability.under_daily_cap", AsyncMock(return_value=False)) as cap:
        result = await m.report_user_info(text=text, uid="alice")
    assert result["saved"] is True
    args = ingest.await_args
    assert args.args[:4] == (pool, arq, "alice", "claude")
    assert args.args[4][0].content == text.strip()
    assert args.kwargs == {"min_chars": 8}
    cap.assert_not_awaited()


async def test_free_text_allows_empty_typed_fields_and_normalizes_input():
    with patch.object(m, "_get_pool", AsyncMock()), \
         patch.object(m, "_get_arq", AsyncMock()), \
         patch.object(m, "ingest_turns", AsyncMock(return_value=(1, 0))) as ingest:
        result = await m.report_user_info(
            text="  I am learning Rust.  ", role=" \n ", notes="  ", goals="",
            skills=[], tools=["  "], uid="alice",
        )
    assert result["saved"] is True
    assert ingest.await_args.args[3] == "claude"
    assert ingest.await_args.args[4][0].content == "I am learning Rust."


async def test_blank_text_retains_typed_mode_and_daily_cap(monkeypatch):
    monkeypatch.setattr(settings, "feature_s05_typed_capture", True)
    with patch.object(m, "_get_pool", AsyncMock()), \
         patch("app.services.findability.under_daily_cap", AsyncMock(return_value=False)) as cap, \
         patch.object(m, "ingest_turns", AsyncMock()) as ingest:
        result = await m.report_user_info(text=" \n ", skills=["Rust"], uid="alice")
    assert result["saved"] is False
    assert "daily report cap" in result["reason"]
    cap.assert_awaited_once()
    ingest.assert_not_awaited()


@pytest.mark.parametrize("text", [None, "", " \n "])
async def test_all_empty_write_does_not_enqueue(monkeypatch, text):
    monkeypatch.setattr(settings, "feature_s05_typed_capture", False)
    monkeypatch.setattr(settings, "feature_s05_observe", False)
    with patch.object(m, "_get_pool", AsyncMock()), \
         patch.object(m, "ingest_turns", AsyncMock()) as ingest, \
         patch.object(m, "_get_arq", AsyncMock()) as arq:
        result = await m.report_user_info(text=text, uid="alice")
    assert result["saved"] is False
    ingest.assert_not_awaited()
    arq.assert_not_awaited()


async def test_typed_write_keeps_per_field_and_total_caps(monkeypatch):
    monkeypatch.setattr(settings, "feature_s05_typed_capture", True)
    with patch.object(m, "_get_pool", AsyncMock()), \
         patch("app.services.findability.under_daily_cap", AsyncMock(return_value=True)), \
         patch("app.services.findability.declare_for_review", AsyncMock(return_value=True)) as declare, \
         patch.object(m, "ingest_turns", AsyncMock()) as ingest:
        result = await m.report_user_info(
            tools=["Docker", "Figma", "Notion", "Slack", "Git"],
            languages=["Rust", "Python", "Java", "Go", "Ruby"],
            frameworks=["React", "Django", "FastAPI", "Rails", "Vue"],
            skills=["SQL", "TypeScript"], uid="alice",
        )
    assert result["items_saved"] == 12
    assert declare.await_count == 12
    assert "Git" not in [call.args[3] for call in declare.await_args_list]
    assert "Ruby" not in [call.args[3] for call in declare.await_args_list]
    ingest.assert_not_awaited()


@pytest.mark.parametrize("observe", [False, True])
async def test_typed_capture_disabled_retains_legacy_source_without_direct_writes(monkeypatch, observe):
    monkeypatch.setattr(settings, "feature_s05_typed_capture", False)
    monkeypatch.setattr(settings, "feature_s05_observe", observe)
    with patch.object(m, "_get_pool", AsyncMock()), \
         patch.object(m, "_get_arq", AsyncMock()), \
         patch.object(m, "ingest_turns", AsyncMock(return_value=(1, 0))) as ingest, \
         patch("app.services.findability.declare_for_review", AsyncMock()) as declare, \
         patch("app.services.findability.under_daily_cap", AsyncMock()) as cap:
        result = await m.report_user_info(text="  ", role="Engineer", skills=["Rust"], uid="alice")
    assert result["saved"] is True
    assert result["items_saved"] == 1
    assert ingest.await_args.args[3] == "cards_mcp"
    assert any("Rust" in turn.content for turn in ingest.await_args.args[4])
    cap.assert_not_awaited()
    declare.assert_not_awaited()
