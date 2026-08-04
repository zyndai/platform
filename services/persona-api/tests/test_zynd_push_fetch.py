"""
Tests for the corrected inbound-push result retrieval:

- zynd push callbacks are status-only and arrive multiple times per task,
  and ``status.state`` can read "completed" while the payload is still a
  deferral ack. ``_push_result_ready`` must judge readiness from content.
- ``_fetch_and_record_push_result`` must pull the Task with tasks/get,
  record a callback_result ONLY when the result is actually ready, and
  swallow fetch failures (leaving the callback pending for the next push).
"""

from __future__ import annotations

import pytest


# The acceptance ack observed live: state=completed but shortlist=null.
_ACK_TASK = {
    "id": "task-1",
    "kind": "task",
    "status": {"state": "completed", "timestamp": "2026-06-04T06:53:06.319Z"},
    "artifacts": [
        {
            "artifactId": "a1",
            "name": "result",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "delivery": "push",
                        "mode": "search",
                        "response": "Task accepted; shortlist will be POSTed to <webhook> when ready.",
                        "shortlist": None,
                        "taskId": "task-1",
                    },
                }
            ],
        }
    ],
}

_READY_TASK = {
    "id": "task-1",
    "kind": "task",
    "status": {"state": "completed"},
    "artifacts": [
        {
            "name": "result",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "delivery": "push",
                        "mode": "search",
                        "response": "Done",
                        "shortlist": [{"handle": "@fit", "followers": 50000}],
                    },
                }
            ],
        }
    ],
}

_TEXT_TASK = {
    "id": "task-1",
    "status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": "the answer"}]}},
}


# ── _push_result_ready ───────────────────────────────────────────────


def test_acceptance_ack_is_not_ready():
    from agent import a2a_router as r

    ready, reply, structured = r._push_result_ready(_ACK_TASK)
    assert ready is False
    assert reply is None
    assert structured is None


def test_populated_payload_is_ready():
    from agent import a2a_router as r

    ready, reply, structured = r._push_result_ready(_READY_TASK)
    assert ready is True
    assert structured["shortlist"][0]["handle"] == "@fit"


def test_status_message_text_is_ready():
    from agent import a2a_router as r

    ready, reply, structured = r._push_result_ready(_TEXT_TASK)
    assert ready is True
    assert reply == "the answer"


# ── _fetch_and_record_push_result ────────────────────────────────────


def _fake_client_factory(task=None, exc=None):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def get_task(self, url, task_id, **k):
            if exc is not None:
                raise exc
            return task

    return _FakeClient


def _callback():
    return {
        "id": "cb-1",
        "user_id": "user-1",
        "thread_id": "ctx-1",
        "peer_agent_id": "zns:svc:x",
        "peer_task_id": "task-1",
        "peer_a2a_url": "http://svc/a2a/v1",
    }


def _patch(monkeypatch, *, client_factory):
    from agent import a2a_router as r
    from agent.a2a import client as client_mod
    from services import callbacks as cb_service

    monkeypatch.setattr(r, "_persona_keypair", lambda uid: (object(), "zns:me"))
    monkeypatch.setattr(client_mod, "A2AClient", client_factory)

    recorded: list = []
    monkeypatch.setattr(
        cb_service, "record_result",
        lambda **kw: (recorded.append(kw) or "res-1"),
    )
    return r, recorded


@pytest.mark.asyncio
async def test_fetch_records_when_ready(monkeypatch):
    r, recorded = _patch(monkeypatch, client_factory=_fake_client_factory(task=_READY_TASK))

    await r._fetch_and_record_push_result(_callback(), {"taskId": "task-1", "status": {"state": "completed"}}, {})

    assert len(recorded) == 1
    kw = recorded[0]
    assert kw["task_state"] == "completed"
    # structured-only result is serialized; @fit is in the structured payload,
    # not in reply_text (which comes from the "response" field = "Done")
    assert kw["raw_event"]["structured"]["shortlist"][0]["handle"] == "@fit"
    assert kw["raw_event"]["fetched_task"] is _READY_TASK
    assert kw["raw_event"]["structured"]["shortlist"]


@pytest.mark.asyncio
async def test_fetch_skips_when_not_ready(monkeypatch):
    r, recorded = _patch(monkeypatch, client_factory=_fake_client_factory(task=_ACK_TASK))

    await r._fetch_and_record_push_result(_callback(), {"taskId": "task-1", "status": {"state": "completed"}}, {})

    assert recorded == []


@pytest.mark.asyncio
async def test_fetch_swallows_a2a_error(monkeypatch):
    from agent.a2a.client import A2AError

    r, recorded = _patch(
        monkeypatch,
        client_factory=_fake_client_factory(exc=A2AError(code=-32001, message="not found")),
    )

    await r._fetch_and_record_push_result(_callback(), {"taskId": "task-1", "status": {"state": "completed"}}, {})

    assert recorded == []


@pytest.mark.asyncio
async def test_fetch_surfaces_real_failure(monkeypatch):
    failed = {"id": "task-1", "status": {"state": "failed", "message": {"parts": [{"kind": "text", "text": "boom"}]}}}
    r, recorded = _patch(monkeypatch, client_factory=_fake_client_factory(task=failed))

    await r._fetch_and_record_push_result(_callback(), {"taskId": "task-1", "status": {"state": "failed"}}, {})

    assert len(recorded) == 1
    assert recorded[0]["task_state"] == "failed"


@pytest.mark.asyncio
async def test_fetch_records_from_push_body(monkeypatch):
    # Result delivered IN the push body ("shortlist will be POSTed ... when
    # ready"). tasks/get keeps returning the acceptance ack — the body must win.
    r, recorded = _patch(monkeypatch, client_factory=_fake_client_factory(task=_ACK_TASK))

    event = {"taskId": "task-1", "kind": "status-update", "status": {"state": "completed"}}
    wrapper = {
        "kind": "message",
        "parts": [
            {"kind": "data", "data": event},
            {"kind": "data", "data": {"mode": "search", "shortlist": [{"handle": "@fit"}]}},
        ],
    }

    await r._fetch_and_record_push_result(_callback(), event, wrapper)

    assert len(recorded) == 1
    assert recorded[0]["raw_event"]["source"] == "push-body"
    assert "@fit" in recorded[0]["reply_text"]


@pytest.mark.asyncio
async def test_poll_pending_fetches_each_with_task_id(monkeypatch):
    # The fallback poller must fetch every pending call that has a peer task
    # id, and skip ones that don't (nothing to tasks/get by).
    from agent import a2a_router as r
    from services import callbacks as cb_service

    monkeypatch.setattr(cb_service, "list_pending", lambda: [
        {"id": "cb-1", "peer_task_id": "t1"},
        {"id": "cb-2", "peer_task_id": None},
        {"id": "cb-3", "peer_task_id": "t3"},
    ])

    seen: list = []

    async def _fake_fetch(cb, event, wrapper):
        seen.append((cb["id"], event.get("taskId")))

    monkeypatch.setattr(r, "_fetch_and_record_push_result", _fake_fetch)

    n = await r._poll_pending_callbacks()

    assert n == 2
    assert ("cb-1", "t1") in seen
    assert ("cb-3", "t3") in seen
    assert all(c[0] != "cb-2" for c in seen)
