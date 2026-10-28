"""Logs API: a small, authenticated, bounded front for Loki.

Loki's own API has no authentication, takes raw LogQL with no limits and has delete
endpoints, so it stays on loopback. This service turns plain filters (project, env, level,
text, time range) into LogQL, caps what a request can ask for, and needs an API key.

    GET /v1/sources   what is being collected: labels, projects, line counts, last entry
    GET /v1/logs      the log lines, filtered by labels, text and time
    GET /v1/stats     line counts over time, grouped by level / project / ...
    GET /health

Auth: `Authorization: Bearer <key>`; the keys are LOGS_API_KEYS (comma separated).
"""
import asyncio
import hmac
import os
import re
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

LOKI_URL = "http://127.0.0.1:3100"
RETENTION_SECONDS = 14 * 86400          # matches loki/config.yml
DEFAULT_SINCE = "1h"
DEFAULT_LIMIT = 100
MAX_LIMIT = 5000                        # Loki's own per-query cap
MAX_POINTS = 1000                       # for /v1/stats
LOKI_TIMEOUT = 30.0

# Labels a caller may filter on, and the characters a value may use. Values are quoted into
# LogQL, so this is also what keeps a request from injecting query syntax.
FILTER_LABELS = ("source", "env", "project", "level", "container", "process", "stream", "host", "status")
GROUP_LABELS = ("level", "project", "env", "source", "host", "status", "container", "process")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/\- ]{1,100}$")
# A positive whole number and a unit: 30s, 15m, 6h, 2d. Zero is refused, since a 0s step
# would divide by zero and a 0s range is empty.
DURATION = re.compile(r"^([1-9]\d*)([smhd])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

app = FastAPI(title="Zynd logs API", version="1.0.0", description=__doc__)
_bearer = HTTPBearer(auto_error=False)


def _keys() -> list[str]:
    return [k.strip() for k in os.environ.get("LOGS_API_KEYS", "").split(",") if k.strip()]


def require_key(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    keys = _keys()
    if not keys:
        raise HTTPException(503, "no API key is configured (LOGS_API_KEYS)")
    if cred is None or not any(hmac.compare_digest(cred.credentials, k) for k in keys):
        raise HTTPException(401, "missing or wrong API key", headers={"WWW-Authenticate": "Bearer"})


_client: httpx.AsyncClient | None = None


def loki() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=LOKI_URL, timeout=LOKI_TIMEOUT)
    return _client


# ── time ────────────────────────────────────────────────────────────────

def _to_ns(value: str, name: str) -> int:
    """RFC 3339 ('2026-10-28T10:00:00Z') or unix seconds / ms / ns."""
    v = value.strip()
    if v.isdigit():
        n = int(v)
        return n * 10**9 if n < 10**11 else n * 10**6 if n < 10**14 else n
    try:
        return int(datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 10**9)
    except ValueError:
        raise HTTPException(422, f"{name}: expected RFC 3339 (2026-10-28T10:00:00Z) or a unix timestamp")


def duration_seconds(value: str, name: str) -> int:
    m = DURATION.match(value.strip())
    if not m:
        raise HTTPException(422, f"{name}: expected a duration like 30s, 15m, 6h or 2d")
    return int(m.group(1)) * UNIT_SECONDS[m.group(2)]


def resolve_range(since: str | None, start: str | None, end: str | None, now_ns: int | None = None) -> tuple[int, int]:
    now_ns = now_ns or int(datetime.now(timezone.utc).timestamp() * 10**9)
    end_ns = _to_ns(end, "end") if end else now_ns
    if start:
        start_ns = _to_ns(start, "start")
    else:
        start_ns = end_ns - duration_seconds(since or DEFAULT_SINCE, "since") * 10**9
    if start_ns >= end_ns:
        raise HTTPException(422, "the range is empty: start must be before end")
    if (end_ns - start_ns) > RETENTION_SECONDS * 10**9:
        raise HTTPException(422, f"the range is longer than the {RETENTION_SECONDS // 86400} days of logs kept")
    return start_ns, end_ns


# ── LogQL ───────────────────────────────────────────────────────────────

_META = re.compile(r"([\\.+*?()|\[\]{}^$])")


def _quote_meta(s: str) -> str:
    """Escape regex metacharacters like Go's regexp.QuoteMeta (Loki is Go; re.escape would
    also escape spaces, which is valid but makes the queries hard to read)."""
    return _META.sub(r"\\\1", s)


def _logql_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


STATUS = re.compile(r"^(?:[1-5]\d\d|[1-5]xx)$")


def _values(raw: list[str] | None, label: str) -> list[str]:
    """Comma-separated and/or repeated values, checked against the allowed characters."""
    out = []
    for item in raw or []:
        for v in item.split(","):
            v = v.strip()
            if not v:
                continue
            ok = STATUS.match(v) if label == "status" else SAFE_VALUE.match(v)
            if not ok:
                raise HTTPException(422, f"{label}: '{v[:30]}' is not an allowed value")
            out.append(v)
    return out


def build_selector(filters: dict[str, list[str] | None]) -> str:
    matchers = []
    for label in FILTER_LABELS:
        vals = _values(filters.get(label), label)
        if not vals:
            continue
        if label == "status":
            # 404 stays 404; a class like 5xx becomes the regex 5..
            matchers.append(f"status=~{_logql_string('|'.join(v.replace('xx', '..') for v in vals))}")
        elif len(vals) == 1:
            matchers.append(f"{label}={_logql_string(vals[0])}")
        else:
            matchers.append(f"{label}=~{_logql_string('|'.join(_quote_meta(v) for v in vals))}")
    return "{" + (", ".join(matchers) if matchers else 'source=~".+"') + "}"


def build_query(filters, q=None, not_q=None, regex=None) -> str:
    parts = [build_selector(filters)]
    for text in q or []:
        parts.append("|~ " + _logql_string("(?i)" + _quote_meta(text)))
    for text in not_q or []:
        parts.append("!~ " + _logql_string("(?i)" + _quote_meta(text)))
    if regex:
        try:
            re.compile(regex)
        except re.error as e:
            raise HTTPException(422, f"regex: {e}")
        parts.append("|~ " + _logql_string(regex))
    return " ".join(parts)


# ── Loki ────────────────────────────────────────────────────────────────

async def loki_get(path: str, params: dict):
    try:
        r = await loki().get(path, params=params)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Loki is not answering: {type(e).__name__}")
    if r.status_code == 400:
        raise HTTPException(422, f"Loki rejected the query: {r.text[:300]}")
    if r.status_code >= 400:
        raise HTTPException(502, f"Loki returned {r.status_code}")
    return r.json()["data"]


def _rfc3339(ns: int) -> str:
    dt = datetime.fromtimestamp(ns // 10**9, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ns % 10**9:09d}Z"


# ── endpoints ───────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health():
    await loki_get("/loki/api/v1/labels", {})
    return {"status": "ok"}


def _filters(source, env, project, level, container, process, stream, host, status):
    return {"source": source, "env": env, "project": project, "level": level, "container": container,
            "process": process, "stream": stream, "host": host, "status": status}


F = {  # shared filter parameters, repeated or comma-separated
    "source": Query(None, description="docker, pm2 or caddy"),
    "env": Query(None, description="prod, dev, shared or test"),
    "project": Query(None, description="cards-api, memory-api, mcp, worker, cards-web, persona-api, ..."),
    "level": Query(None, description="debug, info, warning or error"),
    "container": Query(None, description="Docker container name (source=docker)"),
    "process": Query(None, description="pm2 process name (source=pm2)"),
    "stream": Query(None, description="pm2 stream: out (stdout) or error (stderr)"),
    "host": Query(None, description="Caddy hostname (source=caddy)"),
    "status": Query(None, description="Caddy HTTP status: 404, or a class like 5xx (source=caddy)"),
}


@app.get("/v1/logs", dependencies=[Depends(require_key)])
async def logs(
    source: list[str] | None = F["source"], env: list[str] | None = F["env"],
    project: list[str] | None = F["project"], level: list[str] | None = F["level"],
    container: list[str] | None = F["container"], process: list[str] | None = F["process"],
    stream: list[str] | None = F["stream"], host: list[str] | None = F["host"],
    status: list[str] | None = F["status"],
    q: list[str] | None = Query(None, description="Lines containing this text (case-insensitive). Repeat to require all."),
    not_q: list[str] | None = Query(None, description="Lines NOT containing this text. Repeat to exclude several."),
    regex: str | None = Query(None, description="Lines matching this regular expression (RE2)."),
    since: str | None = Query(None, description=f"Relative range ending now (or at `end`): 30s, 15m, 6h, 2d. Default {DEFAULT_SINCE}."),
    start: str | None = Query(None, description="Range start: RFC 3339 or unix seconds. Overrides `since`."),
    end: str | None = Query(None, description="Range end (exclusive), default now. Also the page cursor: pass `next.end` from a truncated response."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    order: str = Query("desc", pattern="^(asc|desc)$", description="desc = newest first"),
):
    start_ns, end_ns = resolve_range(since, start, end)
    query = build_query(_filters(source, env, project, level, container, process, stream, host, status), q, not_q, regex)
    entries = await _fetch_entries(query, start_ns, end_ns, limit, order)
    truncated = len(entries) >= limit
    next_end = None
    if truncated and order == "desc":
        entries, next_end = await _page_boundary(query, entries)
    for e in entries:
        e["ts"] = _rfc3339(int(e["ts_ns"]))
    out = {"query": query, "start": _rfc3339(start_ns), "end": _rfc3339(end_ns), "order": order,
           "count": len(entries), "truncated": truncated, "entries": entries}
    if next_end is not None:
        out["next"] = {"end": str(next_end)}
    return out


async def _fetch_entries(query: str, start_ns: int, end_ns: int, limit: int, order: str) -> list[dict]:
    data = await loki_get("/loki/api/v1/query_range", {
        "query": query, "start": start_ns, "end": end_ns, "limit": limit,
        "direction": "backward" if order == "desc" else "forward"})
    entries = []
    for st in data["result"]:
        for ts, line in st["values"]:
            entries.append({"ts_ns": ts, "labels": st["stream"], "line": line})
    entries.sort(key=lambda e: int(e["ts_ns"]), reverse=(order == "desc"))
    return entries[:limit]


async def _page_boundary(query: str, entries: list[dict]) -> tuple[list[dict], int]:
    """Where a truncated newest-first page ends, and the `end` that continues it.

    Loki's `end` is exclusive and it has no cursor within a nanosecond, and when several entries
    share the page's oldest timestamp, which of them made the cut is arbitrary. Using that
    timestamp as the next `end` would skip the ones that didn't. So the whole oldest-timestamp
    group is held back and the next page ends just past it (ts + 1), which returns that group in
    full and nothing newer: no entry is lost or repeated.

    If the page is that one group, holding it back would hand out the same cursor forever, so the
    group is fetched on its own (a 1 ns range, up to MAX_LIMIT entries) and the next page starts
    below it. Only a single nanosecond holding more than MAX_LIMIT entries can still lose lines.
    """
    oldest = int(entries[-1]["ts_ns"])
    newer = [e for e in entries if int(e["ts_ns"]) != oldest]
    if newer:
        return newer, oldest + 1
    return await _fetch_entries(query, oldest, oldest + 1, MAX_LIMIT, "desc"), oldest


@app.get("/v1/stats", dependencies=[Depends(require_key)])
async def stats(
    source: list[str] | None = F["source"], env: list[str] | None = F["env"],
    project: list[str] | None = F["project"], level: list[str] | None = F["level"],
    container: list[str] | None = F["container"], process: list[str] | None = F["process"],
    stream: list[str] | None = F["stream"], host: list[str] | None = F["host"],
    status: list[str] | None = F["status"],
    q: list[str] | None = Query(None), not_q: list[str] | None = Query(None), regex: str | None = Query(None),
    since: str | None = Query(None), start: str | None = Query(None), end: str | None = Query(None),
    group_by: str = Query("level", description=f"One of {', '.join(GROUP_LABELS)}"),
    step: str | None = Query(None, description="Bucket size (30s, 5m, 1h). Default: the range split into about 100 buckets."),
):
    if group_by not in GROUP_LABELS:
        raise HTTPException(422, f"group_by: must be one of {', '.join(GROUP_LABELS)}")
    start_ns, end_ns = resolve_range(since, start, end)
    span_s = (end_ns - start_ns) // 10**9
    step_s = duration_seconds(step, "step") if step else max(15, span_s // 100)
    if span_s // step_s > MAX_POINTS:
        raise HTTPException(422, f"step is too small for this range: more than {MAX_POINTS} points")
    selector = build_query(_filters(source, env, project, level, container, process, stream, host, status), q, not_q, regex)
    query = f"sum by ({group_by}) (count_over_time({selector} [{step_s}s]))"
    data = await loki_get("/loki/api/v1/query_range", {"query": query, "start": start_ns, "end": end_ns, "step": f"{step_s}s"})
    series = [{"labels": s["metric"], "points": [[float(t), int(float(v))] for t, v in s["values"]]} for s in data["result"]]
    return {"query": query, "start": _rfc3339(start_ns), "end": _rfc3339(end_ns), "step_seconds": step_s,
            "group_by": group_by, "series": series}


@app.get("/v1/sources", dependencies=[Depends(require_key)])
async def sources(since: str = Query("24h", description="Window for the line counts and last-seen times")):
    """What is being collected: the label values you can filter on, and per source/env/project
    the line counts by level and the time of the latest entry."""
    start_ns, end_ns = resolve_range(since, None, None)
    window = {"start": start_ns, "end": end_ns}
    names = ("source", "env", "project", "level", "container", "process", "host")
    label_data, counts = await asyncio.gather(
        asyncio.gather(*[loki_get(f"/loki/api/v1/label/{n}/values", window) for n in names]),
        loki_get("/loki/api/v1/query", {
            "query": f'sum by (source, env, project, level) (count_over_time({{source=~".+"}} [{(end_ns - start_ns) // 10**9}s]))',
            "time": end_ns}))
    groups: dict[tuple, dict] = {}
    for r in counts["result"]:
        m = r["metric"]
        key = (m.get("source", ""), m.get("env", ""), m.get("project", ""))
        g = groups.setdefault(key, {"source": key[0], "env": key[1], "project": key[2], "lines": 0, "by_level": {}})
        n = int(float(r["value"][1]))
        g["lines"] += n
        g["by_level"][m.get("level", "none")] = n

    async def latest(g):
        sel = build_selector({"source": [g["source"]], "env": [g["env"]] if g["env"] else None, "project": [g["project"]] if g["project"] else None})
        data = await loki_get("/loki/api/v1/query_range", {"query": sel, "start": start_ns, "end": end_ns, "limit": 1, "direction": "backward"})
        ts = [int(v[0]) for st in data["result"] for v in st["values"]]
        g["last_entry"] = _rfc3339(max(ts)) if ts else None

    await asyncio.gather(*[latest(g) for g in groups.values()])
    return {"window": {"start": _rfc3339(start_ns), "end": _rfc3339(end_ns)},
            "retention_days": RETENTION_SECONDS // 86400,
            "labels": dict(zip(names, label_data)),
            "streams": sorted(groups.values(), key=lambda g: (g["source"], g["env"], g["project"]))}
