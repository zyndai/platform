"""Group memory and Card assistant reply wiring. No database or model calls."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import network
import config
from services import group_agent, group_memory


USER = "00000000-0000-0000-0000-000000000001"
BOB = "00000000-0000-0000-0000-000000000002"
CARA = "00000000-0000-0000-0000-000000000003"
GROUP = "00000000-0000-0000-0000-000000000010"


def test_remember_hash_is_stable():
    assert group_memory.content_hash(" ship Friday ") == group_memory.content_hash(" ship Friday ")
    assert group_memory.content_hash("ship Friday") != group_memory.content_hash("ship Monday")


def test_mentions_queue_at_most_two_members_and_skip_the_sender(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_GROUP_AGENT_REPLIES", True)
    monkeypatch.setattr(network.group_memory, "members", lambda _: [
        {"user_id": USER, "handle": "alice", "name": "Alice"},
        {"user_id": BOB, "handle": "bob", "name": "Bob"},
        {"user_id": CARA, "handle": "cara", "name": "Cara"},
    ])
    queued = {}
    monkeypatch.setattr(
        network.group_memory, "enqueue_agent_replies",
        lambda message, users: queued.update(message=message, users=users) or {"enqueued": len(users)},
    )
    updates = []
    sb = SimpleNamespace(table=lambda _: SimpleNamespace(
        update=lambda payload: SimpleNamespace(eq=lambda *_: SimpleNamespace(execute=lambda: updates.append(payload))),
    ))
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    result = {"message": {"id": "message-1", "content": "@bob @cara @alice please look"}}
    network._enqueue_group_mentions(USER, GROUP, result)
    assert queued == {"message": "message-1", "users": [BOB, CARA]}
    assert result["agent_replies"] == 2
    assert result["message"]["mentions"] == [BOB, CARA]
    assert updates == [{"mentions": [BOB, CARA]}]


def test_mentions_do_nothing_when_agent_replies_are_off(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_GROUP_AGENT_REPLIES", False)
    called = []
    monkeypatch.setattr(network.group_memory, "members", lambda _: called.append("members") or [])
    result = {"message": {"id": "m", "content": "@bob hi"}}
    network._enqueue_group_mentions(USER, GROUP, result)
    assert called == []
    assert "agent_replies" not in result


def test_email_addresses_are_not_mentions(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_GROUP_AGENT_REPLIES", True)
    monkeypatch.setattr(network.group_memory, "members", lambda _: [{"user_id": BOB, "handle": "example"}])
    called = []
    monkeypatch.setattr(network.group_memory, "enqueue_agent_replies", lambda *_: called.append(True) or {"enqueued": 1})
    result = {"message": {"id": "m", "content": "write to me@example.com"}}
    network._enqueue_group_mentions(USER, GROUP, result)
    assert called == []
    assert result["agent_replies"] == 0


def test_semantic_search_uses_the_embedding_and_membership_check(monkeypatch):
    seen = {}
    monkeypatch.setattr(group_memory, "_require_member", lambda group, user: seen.update(group=group, user=user))
    monkeypatch.setattr(group_memory, "_embed", lambda text: [0.1] * 1536)
    monkeypatch.setattr(group_memory, "_rpc_result", lambda name, params: seen.update(name=name, params=params) or [{"content": "Friday"}])
    result = group_memory.search_memory(USER, GROUP, "when are we shipping?", 5)
    assert result["results"] == [{"content": "Friday"}]
    assert seen["name"] == "network_group_memory_search"
    assert seen["params"]["p_query_embedding"][:2] == [0.1, 0.1]
    assert seen["params"]["p_limit"] == 5


def test_remember_reads_the_message_then_calls_the_atomic_rpc(monkeypatch):
    seen = {}
    monkeypatch.setattr(group_memory, "_require_member", lambda *_: None)
    monkeypatch.setattr(group_memory, "_message_content", lambda group, message: ("Decision: ship Friday", "user"))
    monkeypatch.setattr(group_memory, "_embed", lambda text: [0.2] * 1536)
    monkeypatch.setattr(group_memory, "_rpc_result", lambda name, params: seen.update(name=name, params=params) or {"memory": {"id": "memory-1"}})
    result = group_memory.remember_message(USER, GROUP, "message-1")
    assert result == {"memory": {"id": "memory-1"}}
    assert seen["name"] == "network_group_memory_remember"
    assert seen["params"]["p_content_hash"] == group_memory.content_hash("Decision: ship Friday")
    assert seen["params"]["p_message"] == "message-1"


def test_agent_reply_cannot_be_remembered(monkeypatch):
    monkeypatch.setattr(group_memory, "_require_member", lambda *_: None)
    monkeypatch.setattr(group_memory, "_message_content", lambda group, message: ("AI reply", "agent"))
    with pytest.raises(HTTPException) as error:
        group_memory.remember_message(USER, GROUP, "message-1")
    assert error.value.status_code == 422


def test_empty_manual_fact_is_rejected_before_the_database(monkeypatch):
    monkeypatch.setattr(group_memory, "_require_member", lambda *_: None)
    with pytest.raises(HTTPException) as error:
        group_memory.add_fact(USER, GROUP, "   ")
    assert error.value.status_code == 422


def test_agent_prompt_is_explicitly_not_the_person():
    ctx = {
        "group": {"name": "API builders", "description": "Shipping APIs"},
        "mentioned": {"name": "Bob", "handle": "bob"},
        "trigger": {"content": "@bob can you review?", "sender_user_id": USER},
        "members": [{"user_id": USER, "name": "Alice", "handle": "alice"}],
        "recent": [],
        "summary": None,
        "facts": [],
        "public_memory": {"connected": True, "facts": [{"predicate": "is_working_on", "object": "Payments API"}]},
    }
    prompt = group_agent._system_prompt(ctx)
    assert "You are not Bob" in prompt
    assert "Never claim to be human" in prompt
    assert "Never reveal private memory" in prompt
    initial = group_agent._initial_prompt(ctx)
    assert "Payments API" in initial
    assert "Tagged by: Alice" in initial


def test_summary_parser_accepts_json_and_falls_back_to_text():
    summary, facts = group_agent._parse_summary('{"summary":"Shipping Friday","facts":["Use the staging key"]}')
    assert summary == "Shipping Friday"
    assert facts == ["Use the staging key"]
    summary, facts = group_agent._parse_summary("plain summary")
    assert summary == "plain summary"
    assert facts == []


def test_group_agent_search_tool_stays_inside_the_group(monkeypatch):
    seen = {}
    monkeypatch.setattr(group_memory, "search_memory", lambda user, group, query, limit: seen.update(
        user=user, group=group, query=query, limit=limit,
    ) or {"results": [{"content": "Friday"}]})
    ctx = {
        "group": {"id": GROUP},
        "mentioned": {"user_id": BOB},
        "members": [],
    }
    result = group_agent._tool_result("search_group_memory", {"query": "ship date", "limit": 4}, ctx)
    assert result == {"results": [{"content": "Friday"}]}
    assert seen == {"user": BOB, "group": GROUP, "query": "ship date", "limit": 4}


def test_summary_worker_saves_summary_and_facts(monkeypatch):
    seen = {"facts": []}
    monkeypatch.setattr(group_memory, "group_info", lambda _: {"message_count": 40})
    monkeypatch.setattr(group_memory, "members", lambda _: [])
    monkeypatch.setattr(group_memory, "messages_after", lambda *_: [
        {"seq": 39, "sender_user_id": USER, "sender_kind": "user", "content": "ship Friday"},
        {"seq": 40, "sender_user_id": USER, "sender_kind": "user", "content": "Alice owns launch"},
    ])
    monkeypatch.setattr(group_memory, "summary", lambda _: {"content": "Older context"})
    monkeypatch.setattr(group_memory, "set_summary", lambda group, content, seq, meta: seen.update(
        group=group, content=content, seq=seq, meta=meta,
    ) or {"memory": {"id": "summary-1"}})
    monkeypatch.setattr(group_memory, "add_system_fact", lambda group, fact, meta: seen["facts"].append((fact, meta)))
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content='{"summary":"Shipping Friday; Alice owns launch","facts":["Ship Friday","Alice owns launch"]}',
    ))])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
    monkeypatch.setattr(config, "get_llm_client", lambda: fake)

    group_agent._summarize_group({"group_id": GROUP, "last_summarized_seq": 0})
    assert seen["group"] == GROUP
    assert seen["seq"] == 40
    assert "Shipping Friday" in seen["content"]
    assert [fact for fact, _ in seen["facts"]] == ["Ship Friday", "Alice owns launch"]


def _client(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "memory-network-test")
    app = FastAPI()
    app.include_router(network.router, prefix="/cards")
    return TestClient(app)


def test_group_memory_endpoint_is_gated_by_the_flag(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_GROUP_MEMORY", False)
    app = _client(monkeypatch)
    response = app.get(
        f"/cards/network/groups/{GROUP}/memory",
        headers={"Authorization": "Bearer memory-network-test", "X-Zynd-User": USER},
    )
    assert response.status_code == 503


def test_group_memory_endpoint_uses_the_bound_user(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_GROUP_MEMORY", True)
    seen = {}
    monkeypatch.setattr(network.group_memory, "list_memory", lambda user, group, limit: seen.update(
        user=user, group=group, limit=limit,
    ) or {"summary": None, "facts": []})
    app = _client(monkeypatch)
    response = app.get(
        f"/cards/network/groups/{GROUP}/memory",
        headers={"Authorization": "Bearer memory-network-test", "X-Zynd-User": USER},
    )
    assert response.status_code == 200
    assert seen == {"user": USER, "group": GROUP, "limit": 30}


def test_agent_preference_round_trip_uses_the_bound_user(monkeypatch):
    seen = {}
    monkeypatch.setattr(network.group_memory, "get_agent_preference", lambda user: {"enabled": True, "user": user})
    monkeypatch.setattr(network.group_memory, "set_agent_preference", lambda user, enabled: seen.update(
        user=user, enabled=enabled,
    ) or {"enabled": enabled})
    app = _client(monkeypatch)
    headers = {"Authorization": "Bearer memory-network-test", "X-Zynd-User": USER}
    assert app.get("/cards/network/agent-preferences", headers=headers).json()["user"] == USER
    assert app.put("/cards/network/agent-preferences", json={"enabled": False}, headers=headers).json()["enabled"] is False
    assert seen == {"user": USER, "enabled": False}
