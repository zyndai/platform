"""
Regression tests for the per-turn tool idempotency ledger.

The Wave-1 ledger added raw-args signatures to the EXECUTION ledger at the
iteration boundary. For tools whose schema has no user_id/conversation_id
(e.g. internet_search, webpage_scrape, search_zynd_services) the raw
signature equals the canonical one, so the FIRST call of the turn was
treated as already-executed and skipped — the "every search tool blocked,
it thinks the same query already ran" bug. These tests pin the fix: the
request-side set and the execution-side set are separate, so a first call
always executes and only genuine re-requests are skipped.
"""

from __future__ import annotations

import asyncio
import uuid

from agent import orchestrator


class _ScriptedProvider:
    """Replays a fixed script: (text, tool_calls) per turn."""

    def __init__(self, script):
        self.script = list(script)

    def chat_with_tools(self, messages, tools):
        text, calls = self.script.pop(0)
        return text, calls

    def build_assistant_tool_message(self, content, tool_calls):
        return {"role": "assistant", "content": content or "", "tool_calls": tool_calls}

    def build_tool_result_message(self, tool_call_id, result, tool_name="unknown"):
        return {"role": "tool", "tool_call_id": tool_call_id, "content": result}


def _patch_infra(provider, fake_call):
    orchestrator._get_provider = lambda: provider
    orchestrator.mcp_server.call = fake_call
    orchestrator._persist_chat_message = lambda *a, **k: None
    orchestrator.list_connected_providers = lambda uid: []
    orchestrator.is_linkedin_scraped = lambda uid: False
    orchestrator._format_user_brief = lambda *a, **k: "Test user brief"

    async def _noop_ingest(*a, **k):
        pass

    orchestrator.ingest_conversation = _noop_ingest
    orchestrator._load_history_from_db = lambda *a, **k: []


def _run_turn(provider, fake_call, message="do the thing"):
    _patch_infra(provider, fake_call)
    return asyncio.run(
        orchestrator.handle_user_message(
            user_id=str(uuid.uuid4()),
            message=message,
            conversation_id=f"conv-{uuid.uuid4()}",
        )
    )


def test_first_call_of_no_injection_tool_is_executed():
    """internet_search has no user_id param — its FIRST call must run."""
    executed = []

    def fake_call(fn_name, fn_args):
        executed.append((fn_name, fn_args))
        return {"status": "success", "results": ["gold is up"]}

    provider = _ScriptedProvider(
        [
            ("", [{"id": "tc_1", "name": "internet_search", "arguments": {"query": "gold price today", "num_results": 5}}]),
            ("Here is the answer.", None),
        ]
    )
    result = _run_turn(provider, fake_call)

    assert executed == [("internet_search", {"query": "gold price today", "num_results": 5})], executed
    assert result["actions_taken"][0]["tool"] == "internet_search"
    assert result["actions_taken"][0]["result"].get("status") == "success"


def test_identical_repeat_request_is_skipped_not_blocked_on_first():
    """Two identical requests in the SAME turn: first executes, second is
    deduped at the boundary (never a fake first-time skip)."""
    executed = []

    def fake_call(fn_name, fn_args):
        executed.append(fn_args)
        return {"status": "success"}

    provider = _ScriptedProvider(
        [
            (
                "",
                [
                    {"id": "tc_1", "name": "webpage_scrape", "arguments": {"url": "https://x.com"}},
                    {"id": "tc_2", "name": "webpage_scrape", "arguments": {"url": "https://x.com"}},
                ],
            ),
            ("done.", None),
        ]
    )
    result = _run_turn(provider, fake_call)

    assert executed == [{"url": "https://x.com"}], executed
    assert len(result["actions_taken"]) == 1


def test_different_args_same_tool_both_execute():
    """Different queries to the same tool are distinct work — both run."""
    executed = []

    def fake_call(fn_name, fn_args):
        executed.append(fn_args)
        return {"status": "success"}

    provider = _ScriptedProvider(
        [
            (
                "",
                [
                    {"id": "tc_1", "name": "internet_search", "arguments": {"query": "gold"}},
                    {"id": "tc_2", "name": "internet_search", "arguments": {"query": "silver"}},
                ],
            ),
            ("done.", None),
        ]
    )
    result = _run_turn(provider, fake_call, message="metals please")

    assert len(executed) == 2, executed
    assert len(result["actions_taken"]) == 2
    assert executed[0] != executed[1]


def test_injected_args_tools_still_dedup_by_canonical_signature():
    """A re-request whose raw kwargs differ only by injected fields must
    still be caught by the execution-side ledger (second call skipped)."""
    executed = []

    def fake_call(fn_name, fn_args):
        executed.append(fn_args)
        return {"status": "success", "results": []}

    user_id = str(uuid.uuid4())
    provider = _ScriptedProvider(
        [
            # search_zynd_network HAS user_id — first call omits it (injected),
            # second call passes it explicitly: different raw, same canonical.
            ("", [{"id": "tc_1", "name": "search_zynd_network", "arguments": {"query": "gold"}}]),
            ("", [{"id": "tc_2", "name": "search_zynd_network", "arguments": {"query": "gold", "user_id": user_id}}]),
            ("done.", None),
        ]
    )
    _patch_infra(provider, fake_call)
    asyncio.run(
        orchestrator.handle_user_message(
            user_id=user_id,
            message="network please",
            conversation_id=f"conv-{uuid.uuid4()}",
        )
    )

    assert len(executed) == 1, executed