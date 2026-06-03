"""
Tests for the hardened Zynd agent/service calling paths:

- ``A2AClient.send`` must add ``configuration.blocking=true`` on the sync
  (non-push) path and only ``pushNotificationConfig`` on the push path.
- ``call_zynd_service`` must send ``blocking=true`` and map every A2A task
  state / JSON-RPC error to the right ``status`` (the SDK returns failures
  as Task{state:"failed"|"rejected"}, NOT as thrown errors).
- ``call_zynd_agent`` must dispatch SIGNED, return ``dispatched`` for the
  async (PUSH) transport without blocking, and classify an inline (SEND)
  reply with the same taxonomy as a service call.
"""

from __future__ import annotations

import json

import pytest


# ── A2AClient.send: blocking flag ────────────────────────────────────


class _FakeAsyncResp:
    def __init__(self, envelope):
        self._envelope = envelope

    def raise_for_status(self):
        return None

    def json(self):
        return self._envelope


def _fake_async_client_factory(captured, envelope):
    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["body"] = json
            return _FakeAsyncResp(envelope)

    return _FakeAsyncClient


_COMPLETED_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": "x",
    "result": {"kind": "task", "id": "t", "status": {"state": "completed"}},
}


@pytest.mark.asyncio
async def test_send_sets_blocking_on_sync_path(monkeypatch):
    from agent.a2a import client as client_mod

    captured: dict = {}
    monkeypatch.setattr(client_mod, "sign_message", lambda msg, *a, **k: msg)
    monkeypatch.setattr(
        client_mod.httpx, "AsyncClient",
        _fake_async_client_factory(captured, _COMPLETED_ENVELOPE),
    )

    c = client_mod.A2AClient(keypair=object(), entity_id="zns:me")
    await c.send("http://peer/a2a/v1", context_id="ctx", text="hi")

    assert captured["body"]["params"]["configuration"] == {"blocking": True}


@pytest.mark.asyncio
async def test_send_push_omits_blocking(monkeypatch):
    from agent.a2a import client as client_mod

    captured: dict = {}
    monkeypatch.setattr(client_mod, "sign_message", lambda msg, *a, **k: msg)
    monkeypatch.setattr(
        client_mod.httpx, "AsyncClient",
        _fake_async_client_factory(captured, _COMPLETED_ENVELOPE),
    )

    c = client_mod.A2AClient(keypair=object(), entity_id="zns:me")
    await c.send(
        "http://peer/a2a/v1",
        context_id="ctx",
        text="hi",
        push_url="http://me/cb",
        push_token="tok",
    )

    cfg = captured["body"]["params"]["configuration"]
    assert "pushNotificationConfig" in cfg
    assert "blocking" not in cfg


# ── call_zynd_service: blocking + status taxonomy ────────────────────


class _FakeSyncResp:
    def __init__(self, envelope):
        self._envelope = envelope

    def raise_for_status(self):
        return None

    def json(self):
        return self._envelope


def _fake_sync_client_factory(captured, envelope):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            captured["url"] = url
            captured["body"] = json
            return _FakeSyncResp(envelope)

    return _FakeClient


def _service_task_envelope(state, text=""):
    msg = {"parts": [{"kind": "text", "text": text}]} if text else {}
    return {
        "jsonrpc": "2.0",
        "result": {"id": "task-1", "status": {"state": state, "message": msg}},
    }


def _patch_service_http(monkeypatch, captured, envelope):
    from mcp.tools import zynd_services as svc

    monkeypatch.setattr(
        svc, "get_zynd_service_card",
        lambda eid: {"status": "success", "url": "http://svc/a2a/v1"},
    )
    monkeypatch.setattr(
        svc.httpx, "Client", _fake_sync_client_factory(captured, envelope)
    )
    return svc


def test_call_service_sends_blocking_and_parses_success(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("completed", json.dumps({"ok": True}))
    svc = _patch_service_http(monkeypatch, captured, envelope)

    out = svc.call_zynd_service("zns:svc:x", text="hi")

    assert captured["body"]["params"]["configuration"] == {"blocking": True}
    assert out["status"] == "success"
    assert out["structured_output"] == {"ok": True}


def test_call_service_failed_schema_is_bad_request(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("failed", "ZodError: Required at path query")
    svc = _patch_service_http(monkeypatch, captured, envelope)

    out = svc.call_zynd_service("zns:svc:x", data={"wrong": 1})
    assert out["status"] == "bad_request"


def test_call_service_failed_crash_is_remote_failed(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("failed", "DB connection refused")
    svc = _patch_service_http(monkeypatch, captured, envelope)

    out = svc.call_zynd_service("zns:svc:x", text="hi")
    assert out["status"] == "remote_failed"


def test_call_service_rejected(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("rejected", "No handler is registered")
    svc = _patch_service_http(monkeypatch, captured, envelope)

    out = svc.call_zynd_service("zns:svc:x", text="hi")
    assert out["status"] == "rejected"


def test_call_service_working(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("working")
    svc = _patch_service_http(monkeypatch, captured, envelope)

    out = svc.call_zynd_service("zns:svc:x", text="hi")
    assert out["status"] == "working"


def test_call_service_signs_when_persona_available(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("completed", json.dumps({"ok": True}))
    svc = _patch_service_http(monkeypatch, captured, envelope)

    from mcp.tools import zynd_network as net
    import agent.a2a.auth as auth

    monkeypatch.setattr(net, "_persona_signer", lambda uid: ("KP", "zns:me", {"dp": 1}))

    def _fake_sign(msg, keypair, entity_id, **kw):
        msg["metadata"] = {"x-zynd-auth": {"entity_id": entity_id}}
        return msg

    monkeypatch.setattr(auth, "sign_message", _fake_sign)

    out = svc.call_zynd_service("zns:svc:x", text="hi", user_id="user-1")
    sent_msg = captured["body"]["params"]["message"]
    assert sent_msg["metadata"]["x-zynd-auth"]["entity_id"] == "zns:me"
    assert out["status"] == "success"


def test_call_service_unsigned_without_persona(monkeypatch):
    captured: dict = {}
    envelope = _service_task_envelope("completed", json.dumps({"ok": True}))
    svc = _patch_service_http(monkeypatch, captured, envelope)

    from mcp.tools import zynd_network as net

    monkeypatch.setattr(net, "_persona_signer", lambda uid: None)

    out = svc.call_zynd_service("zns:svc:x", text="hi", user_id="user-1")
    sent_msg = captured["body"]["params"]["message"]
    assert "metadata" not in sent_msg  # unsigned fallback, no persona
    assert out["status"] == "success"


def test_call_service_auth_error_routes_to_agent(monkeypatch):
    captured: dict = {}
    envelope = {
        "jsonrpc": "2.0",
        "error": {"code": -32100, "message": "x-zynd-auth required"},
    }
    svc = _patch_service_http(monkeypatch, captured, envelope)

    out = svc.call_zynd_service("zns:svc:x", text="hi")
    assert out["status"] == "auth_required"
    assert "call_zynd_agent" in out["hint"]


# ── call_zynd_agent: signed, async-capable ───────────────────────────


def _patch_agent_deps(monkeypatch, signed_result):
    from mcp.tools import zynd_network as net
    from mcp.tools import zynd_services as svc

    monkeypatch.setattr(
        svc, "get_zynd_service_card",
        lambda eid: {"status": "success", "url": "http://agent/a2a/v1"},
    )
    # call_zynd_agent resolves the signer identity via _persona_signer and
    # does the wire work via _signed_a2a_send — both are stubbed here.
    monkeypatch.setattr(net, "_persona_signer", lambda uid: ("KP", "zns:me", {"dp": 1}))
    monkeypatch.setattr(net, "_signed_a2a_send", lambda **kw: signed_result)
    return net


def test_call_agent_push_returns_dispatched(monkeypatch):
    net = _patch_agent_deps(monkeypatch, {
        "task": {"id": "task-1", "status": {"state": "submitted"}},
        "task_state": "submitted",
        "reply_text": "",
        "transport": "push",
        "callback_id": "cb-1",
        "pending": True,
    })

    out = net.call_zynd_agent("zns:agent", text="run it", user_id="user-1")
    assert out["status"] == "dispatched"
    assert out["callback_id"] == "cb-1"
    assert out["task_id"] == "task-1"


def test_call_agent_inline_send_is_classified(monkeypatch):
    reply = json.dumps({"result": 42})
    net = _patch_agent_deps(monkeypatch, {
        "task": {
            "id": "task-2",
            "status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": reply}]}},
        },
        "task_state": "completed",
        "reply_text": reply,
        "transport": "send",
    })

    out = net.call_zynd_agent("zns:agent", text="run it", user_id="user-1")
    assert out["status"] == "success"
    assert out["structured_output"] == {"result": 42}


def test_call_agent_delivery_failure_passthrough(monkeypatch):
    net = _patch_agent_deps(monkeypatch, {
        "status": "delivery_failed",
        "reply_status": "rejected",
        "error_code": -32100,
        "message": "rejected",
    })

    out = net.call_zynd_agent("zns:agent", text="run it", user_id="user-1")
    assert out["status"] == "delivery_failed"
    assert out["entity_id"] == "zns:agent"


def test_call_agent_requires_user():
    from mcp.tools import zynd_network as net

    out = net.call_zynd_agent("zns:agent", text="run it", user_id="")
    assert out["status"] == "error"
