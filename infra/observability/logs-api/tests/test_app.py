"""Logs API tests: Loki is replaced by an httpx MockTransport, so no Loki is needed.

    cd infra/observability/logs-api && pip install -r requirements.txt pytest && pytest -q
"""
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as logs_api  # noqa: E402

KEY = "test-key-123"
AUTH = {"Authorization": f"Bearer {KEY}"}
NS = 10**9
T0 = 1_793_000_000 * NS      # an arbitrary "now"


@pytest.fixture
def loki(monkeypatch):
    """Mock Loki: `calls` records every request, `responder` is set per test."""
    calls = []
    box = {"respond": lambda req: httpx.Response(200, json={"status": "success", "data": {"result": []}})}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return box["respond"](request)

    monkeypatch.setattr(logs_api, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://loki"))
    monkeypatch.setenv("LOGS_API_KEYS", f"{KEY}, other-key")
    box["calls"] = calls
    return box


@pytest.fixture
def client(loki):
    return TestClient(logs_api.app)


def streams(*entries, labels=None):
    """A Loki query_range answer: one stream holding (ts_ns, line) entries."""
    return {"status": "success", "data": {"resultType": "streams", "result": [
        {"stream": labels or {"project": "cards-api", "env": "prod", "level": "error"},
         "values": [[str(ts), line] for ts, line in entries]}]}}


# ── auth ────────────────────────────────────────────────────────────────

def test_requires_a_valid_key(client):
    assert client.get("/v1/logs").status_code == 401
    assert client.get("/v1/logs", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/v1/logs", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/v1/logs", headers=AUTH).status_code == 200
    assert client.get("/v1/logs", headers={"Authorization": "Bearer other-key"}).status_code == 200


def test_refuses_to_run_open_when_no_key_is_configured(client, monkeypatch):
    monkeypatch.delenv("LOGS_API_KEYS")
    assert client.get("/v1/logs", headers=AUTH).status_code == 503


def test_sources_and_stats_need_a_key_too(client):
    assert client.get("/v1/sources").status_code == 401
    assert client.get("/v1/stats").status_code == 401


# ── query building ──────────────────────────────────────────────────────

def test_builds_logql_from_filters(client, loki):
    r = client.get("/v1/logs?project=cards-api&env=prod&level=error,warning&q=timeout&not_q=health&regex=5%5Cd%5Cd",
                   headers=AUTH)
    assert r.status_code == 200
    q = r.json()["query"]
    assert q == ('{env="prod", project="cards-api", level=~"error|warning"} '
                 '|~ "(?i)timeout" !~ "(?i)health" |~ "5\\\\d\\\\d"')
    sent = loki["calls"][0].url.params
    assert sent["query"] == q and sent["direction"] == "backward" and sent["limit"] == "100"


def test_no_filter_still_makes_a_valid_selector(client):
    assert client.get("/v1/logs", headers=AUTH).json()["query"] == '{source=~".+"}'


def test_status_classes_and_codes(client):
    q = client.get("/v1/logs?source=caddy&status=5xx,404", headers=AUTH).json()["query"]
    assert 'status=~"5..|404"' in q


@pytest.mark.parametrize("bad", ['a"b', "a}{b", "a\nb", "x" * 101, "a|b"])
def test_label_values_cannot_inject_logql(client, bad):
    assert client.get("/v1/logs", params={"project": bad}, headers=AUTH).status_code == 422


def test_text_filters_are_escaped_not_interpreted(client):
    q = client.get("/v1/logs", params={"q": 'x" } | drop (a.b)'}, headers=AUTH).json()["query"]
    # the quote is escaped and the regex metacharacters are literal
    assert q == '{source=~".+"} |~ "(?i)x\\" \\\\} \\\\| drop \\\\(a\\\\.b\\\\)"'


def test_bad_regex_is_a_422(client):
    assert client.get("/v1/logs", params={"regex": "("}, headers=AUTH).status_code == 422


def test_unknown_status_value_is_rejected(client):
    assert client.get("/v1/logs?status=9xx", headers=AUTH).status_code == 422


# ── time ────────────────────────────────────────────────────────────────

def test_since_start_end_and_limits():
    assert logs_api.resolve_range("15m", None, None, now_ns=T0) == (T0 - 900 * NS, T0)
    assert logs_api.resolve_range(None, None, None, now_ns=T0) == (T0 - 3600 * NS, T0)
    s, e = logs_api.resolve_range(None, "2026-10-28T10:00:00Z", "2026-10-28T11:00:00+00:00")
    assert e - s == 3600 * NS
    s, e = logs_api.resolve_range(None, "1793000000", "1793003600")      # unix seconds
    assert (s, e) == (1_793_000_000 * NS, 1_793_003_600 * NS)
    assert logs_api.resolve_range(None, None, str(T0), now_ns=1)[1] == T0   # nanosecond cursor


@pytest.mark.parametrize("params", [
    {"since": "soon"}, {"since": "15"}, {"start": "yesterday"},
    {"start": "2026-10-28T11:00:00Z", "end": "2026-10-28T10:00:00Z"},     # empty
    {"since": "30d"},                                                    # beyond retention
    {"since": "0s"}, {"since": "00m"},                                   # zero length
])
def test_bad_ranges_are_422(client, params):
    assert client.get("/v1/logs", params=params, headers=AUTH).status_code == 422


def test_limit_is_bounded(client):
    assert client.get("/v1/logs?limit=0", headers=AUTH).status_code == 422
    assert client.get("/v1/logs?limit=5001", headers=AUTH).status_code == 422


# ── /v1/logs results ────────────────────────────────────────────────────

def test_entries_are_flattened_sorted_and_stamped(client, loki):
    loki["respond"] = lambda req: httpx.Response(200, json=streams((T0 + 1, "older"), (T0 + 2 * NS + 5, "newer")))
    r = client.get("/v1/logs?limit=10", headers=AUTH).json()
    assert [e["line"] for e in r["entries"]] == ["newer", "older"]          # newest first
    assert r["entries"][0]["ts"].endswith("Z") and r["entries"][0]["labels"]["project"] == "cards-api"
    assert r["count"] == 2 and r["truncated"] is False and "next" not in r
    asc = client.get("/v1/logs?limit=10&order=asc", headers=AUTH).json()
    assert [e["line"] for e in asc["entries"]] == ["older", "newer"]
    assert loki["calls"][-1].url.params["direction"] == "forward"


def test_truncated_pages_with_a_cursor(client, loki):
    loki["respond"] = lambda req: httpx.Response(200, json=streams((T0 + 3, "c"), (T0 + 2, "b")))
    r = client.get("/v1/logs?limit=2", headers=AUTH).json()
    # the oldest timestamp's entries are held back for the next page, which ends just past them
    assert r["truncated"] is True and [e["line"] for e in r["entries"]] == ["c"]
    assert r["next"] == {"end": str(T0 + 3)}
    # the cursor goes back in as `end`
    client.get(f"/v1/logs?limit=2&end={r['next']['end']}", headers=AUTH)
    assert loki["calls"][-1].url.params["end"] == str(T0 + 3)


def loki_window(entries):
    """A Loki that honours start (inclusive), end (exclusive), direction and limit."""
    def respond(req):
        p = req.url.params
        start, end, limit = int(p["start"]), int(p["end"]), int(p["limit"])
        hits = sorted((e for e in entries if start <= e[0] < end), key=lambda e: e[0], reverse=p["direction"] == "backward")
        return httpx.Response(200, json=streams(*hits[:limit]))
    return respond


def page_through(client, limit):
    lines, end, pages = [], T0 + 100, 0
    while True:
        r = client.get("/v1/logs", params={"limit": limit, "start": str(T0), "end": str(end)}, headers=AUTH).json()
        lines += [e["line"] for e in r["entries"]]
        pages += 1
        assert pages < 50, "paging does not advance"
        if "next" not in r:
            return lines
        end = int(r["next"]["end"])


def test_paging_never_skips_or_repeats_entries_that_share_a_timestamp(client, loki):
    # Five entries at T0+5: with limit 3 the first page ends inside that group, which the old
    # cursor (end = oldest ts, exclusive) skipped the rest of.
    entries = [(T0 + 9, "a"), (T0 + 5, "b1"), (T0 + 5, "b2"), (T0 + 5, "b3"), (T0 + 5, "b4"),
               (T0 + 5, "b5"), (T0 + 2, "c"), (T0 + 1, "d")]
    loki["respond"] = loki_window(entries)
    lines = page_through(client, limit=3)
    assert sorted(lines) == sorted(line for _, line in entries)
    assert len(lines) == len(entries)


def test_a_page_that_is_one_timestamp_returns_all_of_it_and_moves_on(client, loki):
    entries = [(T0 + 5, f"b{i}") for i in range(4)] + [(T0 + 1, "d")]
    loki["respond"] = loki_window(entries)
    r = client.get("/v1/logs", params={"limit": 2, "start": str(T0), "end": str(T0 + 100)}, headers=AUTH).json()
    assert sorted(e["line"] for e in r["entries"]) == ["b0", "b1", "b2", "b3"]
    assert r["next"] == {"end": str(T0 + 5)}
    sent = loki["calls"][-1].url.params        # the group was fetched on its own, 1 ns wide
    assert (sent["start"], sent["end"], sent["limit"]) == (str(T0 + 5), str(T0 + 6), str(logs_api.MAX_LIMIT))
    assert page_through(client, limit=2)[-1] == "d"


# ── /v1/stats ───────────────────────────────────────────────────────────

def test_stats_groups_and_buckets(client, loki):
    loki["respond"] = lambda req: httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": [
        {"metric": {"level": "error"}, "values": [[1793000000, "3"], [1793000060, "0"]]}]}})
    r = client.get("/v1/stats?project=cards-api&since=1h&group_by=level&step=1m", headers=AUTH).json()
    assert r["query"] == 'sum by (level) (count_over_time({project="cards-api"} [60s]))'
    assert r["series"] == [{"labels": {"level": "error"}, "points": [[1793000000.0, 3], [1793000060.0, 0]]}]


def test_stats_rejects_bad_group_and_too_many_points(client):
    assert client.get("/v1/stats?group_by=message", headers=AUTH).status_code == 422
    assert client.get("/v1/stats?since=7d&step=10s", headers=AUTH).status_code == 422


@pytest.mark.parametrize("step", ["0s", "0m", "000h"])
def test_stats_rejects_a_zero_step(client, step):
    # 0s used to reach span // step and fail with a ZeroDivisionError (a 500)
    assert client.get("/v1/stats", params={"since": "1h", "step": step}, headers=AUTH).status_code == 422


# ── /v1/sources ─────────────────────────────────────────────────────────

def test_sources_lists_labels_streams_counts_and_last_entry(client, loki):
    def respond(req):
        path = req.url.path
        if "/label/" in path:
            name = path.split("/label/")[1].split("/")[0]
            return httpx.Response(200, json={"status": "success", "data": {"project": ["cards-api", "mcp"]}.get(name, ["x"])})
        if path.endswith("/query"):
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": [
                {"metric": {"source": "docker", "env": "prod", "project": "cards-api", "level": "info"}, "value": [1, "90"]},
                {"metric": {"source": "docker", "env": "prod", "project": "cards-api", "level": "error"}, "value": [1, "10"]},
                {"metric": {"source": "pm2", "env": "dev", "project": "persona-api", "level": "info"}, "value": [1, "5"]}]}})
        return httpx.Response(200, json=streams((T0 + 7, "last line")))      # the last-entry lookup
    loki["respond"] = respond
    r = client.get("/v1/sources?since=6h", headers=AUTH).json()
    assert r["labels"]["project"] == ["cards-api", "mcp"] and r["retention_days"] == 14
    cards = next(s for s in r["streams"] if s["project"] == "cards-api")
    assert cards["lines"] == 100 and cards["by_level"] == {"info": 90, "error": 10}
    assert cards["last_entry"].endswith("Z")
    assert [s["project"] for s in r["streams"]] == ["cards-api", "persona-api"]    # sorted


# ── Loki trouble ────────────────────────────────────────────────────────

def test_loki_400_is_a_422_and_loki_down_is_a_502(client, loki):
    loki["respond"] = lambda req: httpx.Response(400, text="parse error")
    assert client.get("/v1/logs", headers=AUTH).status_code == 422

    def boom(req):
        raise httpx.ConnectError("refused")
    loki["respond"] = boom
    assert client.get("/v1/logs", headers=AUTH).status_code == 502
