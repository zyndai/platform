"""
Tests for the pre-dispatch payload validator in call_zynd_service.

Root cause covered: the model dispatched ``{"symbol": "NIFTY"}`` to a service
whose input_schema required ``ticker`` — the peer rejected it asynchronously
and the user waited for nothing. The validator must block such calls locally
with a machine-readable violations dict so the LLM retries in the same turn.
"""

from __future__ import annotations

import pytest

from mcp.tools.zynd_services import _validate_payload, call_zynd_service


STOCK_SCHEMA = {
    "type": "object",
    "required": ["ticker"],
    "properties": {
        "ticker": {"type": "string", "description": "Index symbol, e.g. NIFTY"},
        "date": {"type": "string"},
    },
}


def test_missing_required_is_blocked():
    v = _validate_payload(STOCK_SCHEMA, {"symbol": "NIFTY"}, "")
    assert v is not None
    assert v["missing_required"] == ["ticker"]
    assert "symbol" in v["unknown_fields"]


def test_wrong_type_is_blocked():
    v = _validate_payload(STOCK_SCHEMA, {"ticker": 50}, "")
    assert v is not None
    assert v["wrong_types"] == {"ticker": {"expected": "string", "got": "int"}}


def test_valid_payload_passes():
    assert _validate_payload(STOCK_SCHEMA, {"ticker": "NIFTY"}, "") is None
    assert _validate_payload(STOCK_SCHEMA, {"ticker": "NIFTY", "date": "2026-08-17"}, "") is None


def test_text_only_call_is_not_blocked():
    # Text-only is the documented route for free-text/envelope schemas —
    # never false-positive block it.
    assert _validate_payload(STOCK_SCHEMA, None, "nifty 50 stats") is None
    assert _validate_payload(STOCK_SCHEMA, {}, "nifty 50 stats") is None


def test_unknown_fields_advisory_when_schema_open():
    # additionalProperties defaults to open — unknown fields ride along
    # (many remotes ignore extras) and are reported, not blocked.
    v = _validate_payload(STOCK_SCHEMA, {"ticker": "NIFTY", "extra": 1}, "")
    assert v is None


def test_unknown_fields_blocked_when_strict():
    strict = {**STOCK_SCHEMA, "additionalProperties": False}
    v = _validate_payload(strict, {"ticker": "NIFTY", "extra": 1}, "")
    assert v is not None
    assert "extra" in v["unknown_fields"]


def test_no_properties_skips_validation():
    assert _validate_payload({"type": "object"}, {"anything": 1}, "") is None


def test_malformed_schema_never_blocks():
    assert _validate_payload({"properties": "garbage"}, {"a": 1}, "") is None
    assert _validate_payload({"properties": {"a": {"type": "weird-type"}}}, {"a": 1}, "") is None
    assert _validate_payload(None, {"a": 1}, "") is None
    assert _validate_payload({"properties": {}}, {}, "") is None


def test_anyof_typed_fields_not_judged():
    schema = {
        "type": "object",
        "required": ["q"],
        "properties": {"q": {"type": ["string", "number"]}},
    }
    assert _validate_payload(schema, {"q": 42}, "") is None


def test_multiple_violations_all_reported():
    v = _validate_payload(
        {**STOCK_SCHEMA, "additionalProperties": False},
        {"symbol": "NIFTY", "junk": True},
        "",
    )
    assert v is not None
    assert v["missing_required"] == ["ticker"]
    assert set(v["unknown_fields"]) == {"symbol", "junk"}

def test_stringified_json_data_is_parsed_not_rejected(monkeypatch):
    """The LLM serialized `data` to a JSON STRING ('{"ticker":"AAPL"}') —
    the tool must parse it back into a dict (schema `data` was generated as
    type:string due to future-annotations, so the model stringified the
    object, and the peer then rejected with "ticker Field required")."""
    card = {
        "status": "success",
        "url": "https://example.invalid/a2a/v1",
        "input_schema": {
            "type": "object",
            "required": ["ticker"],
            "properties": {"ticker": {"type": "string"}},
        },
    }
    monkeypatch.setattr(
        "mcp.tools.zynd_services.get_zynd_service_card", lambda eid: card
    )
    sent = {}

    def fake_post(url, json=None, timeout=None, headers=None, **_):
        sent["json"] = json
        return _FakeResp(200, {"jsonrpc": "2.0", "result": {}})

    import httpx
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _FakeClient(fake_post))

    result = call_zynd_service(
        entity_id="zns:svc:test", data='{"ticker":"AAPL"}', user_id="u"
    )
    # The string must have been parsed: validation passes (ticker present),
    # so we never return "Nothing to send"/"data must be a JSON object".
    assert result.get("error") != "Nothing to send to the service"
    assert result.get("error") != "data must be a JSON object"
    assert result.get("status") == "success" or "dispatched" in str(result.get("status", "")) or result.get("status") is not None
    assert isinstance(sent.get("json", {}).get("params", {}).get("message", {}).get("parts", [{}])[0].get("data"), dict)


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, post_fn):
        self._post = post_fn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, timeout=None, headers=None, **kw):
        return self._post(url, json=json, timeout=timeout, headers=headers)
