"""A tiny in-memory stand-in for the supabase-py query builder, enough for the Cards network tests.

Supports the calls the network services make: table().select(cols, count=) / insert / update /
upsert / delete with eq, neq, gte, lte, in_, is_, not_.is_, order, limit, then execute().
Rows are plain dicts; inserts get an id and created_at like the real tables do.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


class _Query:
    def __init__(self, db: "FakeSupabase", name: str):
        self.db, self.name = db, name
        self.op, self.payload, self.count_mode = "select", None, None
        self.filters: list = []
        self.order_by: tuple[str, bool] | None = None
        self.max_rows: int | None = None
        self.window: tuple[int, int] | None = None
        self._negate = False

    # builders
    def select(self, cols="*", count=None):
        self.op, self.count_mode = "select", count
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self.op, self.payload = "upsert", (payload, on_conflict, ignore_duplicates)
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def neq(self, col, val):
        self.filters.append(lambda r: r.get(col) != val)
        return self

    def gte(self, col, val):
        self.filters.append(lambda r: r.get(col) is not None and str(r[col]) >= str(val))
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: r.get(col) is not None and str(r[col]) <= str(val))
        return self

    def in_(self, col, vals):
        vals = list(vals)
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def or_(self, expr):
        """`col.eq.value,col.eq.value` — the only form the network services use."""
        parts = []
        for clause in expr.split(","):
            col, op, val = clause.split(".", 2)
            assert op == "eq", f"fake or_ only supports eq, got {op}"
            parts.append((col, val.strip('"')))
        self.filters.append(lambda r: any(str(r.get(c)) == v for c, v in parts))
        return self

    def is_(self, col, val):
        negate = self._negate
        self._negate = False
        want_null = val in (None, "null")
        self.filters.append(lambda r: ((r.get(col) is None) == want_null) != negate)
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def order(self, col, desc=False, nullsfirst=None):
        self.order_by = (col, desc)
        return self

    def limit(self, n):
        self.max_rows = n
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    # execution
    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        matches = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = [self.db.new_row(self.name, item) for item in items]
            return SimpleNamespace(data=[dict(r) for r in out], count=len(out))
        if self.op == "upsert":
            payload, on_conflict, ignore = self.payload
            items = payload if isinstance(payload, list) else [payload]
            out = []
            for item in items:
                keys = [k.strip() for k in (on_conflict or "").split(",") if k.strip()]
                hit = next((r for r in rows if keys and all(r.get(k) == item.get(k) for k in keys)), None)
                if hit is None:
                    out.append(self.db.new_row(self.name, item))
                elif not ignore:
                    hit.update(item)
                    out.append(hit)
            return SimpleNamespace(data=[dict(r) for r in out], count=len(out))
        if self.op == "update":
            for r in matches:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in matches], count=len(matches))
        if self.op == "delete":
            for r in matches:
                rows.remove(r)
            return SimpleNamespace(data=[dict(r) for r in matches], count=len(matches))
        if self.order_by:
            col, desc = self.order_by
            matches.sort(key=lambda r: (r.get(col) is None, str(r.get(col))), reverse=desc)
        total = len(matches)
        if self.window is not None:
            matches = matches[self.window[0]: self.window[1] + 1]
        if self.max_rows is not None:
            matches = matches[: self.max_rows]
        return SimpleNamespace(data=[dict(r) for r in matches], count=total if self.count_mode else None)


class FakeSupabase:
    def __init__(self, **tables):
        self.tables: dict[str, list[dict]] = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def new_row(self, name: str, item: dict) -> dict:
        row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **item}
        if name == "connection_invites":
            row.setdefault("status", "pending")
            row.setdefault("expires_at", (datetime.now(timezone.utc) + timedelta(days=60)).isoformat())
            row.setdefault("delivered_at", None)
            row.setdefault("connection_id", None)
        if name == "saved_searches":
            row.setdefault("active", True)
            row.setdefault("seen_handles", [])
            row.setdefault("last_notified_at", None)
        if name == "card_reports":
            row.setdefault("status", "open")
        if name == "connections":
            row.setdefault("status", "pending")
            row.setdefault("decided_at", None)
            row.setdefault("updated_at", row["created_at"])
        self.tables.setdefault(name, []).append(row)
        return row

    def rows(self, name: str) -> list[dict]:
        return self.tables.get(name, [])
