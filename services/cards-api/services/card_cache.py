"""One in-process copy of the published cards, for search.

A search used to read the database several times in a row (match_cards, search_cards_fts, the
beacon scan, filter_cards once per relaxed pass, then claimed and the searcher's own card), about
0.3 s each from the box, so a relaxed search took ~6 s over 58 cards. While the corpus is small, one
read every SNAPSHOT_TTL_SECONDS serves every search: the cards parsed once, their embeddings
normalised once, so a cosine is a dot product.

cards-api is the only writer of agent_profile_cards and runs one worker, so its own writes clear the
copy at once (invalidate()); the TTL covers anything else. Above SNAPSHOT_MAX_CARDS the copy would
cost too much memory and pure-Python cosine too much time: snapshot() returns None and search uses
the database functions as before.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SNAPSHOT_TTL_SECONDS = 30.0
SNAPSHOT_MAX_CARDS = 500
_COLUMNS = "id,card,handle,embedding,owner_email,published_at"


@dataclass
class Snapshot:
    rows: list[dict]     # {"id", "handle", "card", "model", "unit", "owner_email", "claimed", "published_at"}
    by_handle: dict[str, dict] = field(default_factory=dict)
    loaded_at: float = 0.0


_lock = threading.Lock()
_snapshot: Snapshot | None = None
_too_big_at: float | None = None             # when the corpus was last found too big to copy


def unit(vector) -> list[float]:
    """The vector scaled to length 1 ([] when empty or zero), from a list or pgvector's JSON text."""
    if isinstance(vector, str):
        try:
            vector = json.loads(vector)
        except (json.JSONDecodeError, ValueError):
            return []
    if not isinstance(vector, list) or not vector:
        return []
    try:
        values = [float(x) for x in vector]
    except (TypeError, ValueError):
        return []
    norm = math.sqrt(sum(x * x for x in values))
    return [x / norm for x in values] if norm else []


def dot(a: list[float], b: list[float]) -> float | None:
    """Cosine of two unit vectors; None when either is missing or they differ in length."""
    if not a or not b or len(a) != len(b):
        return None
    return sum(map(float.__mul__, a, b))


def _load() -> Snapshot | None:
    from models.card import AgentProfileCard
    from services import cards as cards_service

    raw = cards_service.list_published_rows(limit=SNAPSHOT_MAX_CARDS + 1, columns=_COLUMNS)
    if len(raw) > SNAPSHOT_MAX_CARDS:
        return None
    rows: list[dict] = []
    for r in raw:
        try:
            model = AgentProfileCard.model_validate(r.get("card") or {})
        except Exception:  # noqa: BLE001 — a card search cannot read is skipped, as the scorer does
            continue
        if r.get("handle"):
            model.handle = r["handle"]
        owner = (r.get("owner_email") or "").strip()
        rows.append({"id": r.get("id"), "handle": r.get("handle"), "card": r.get("card") or {}, "model": model,
                     "unit": unit(r.get("embedding")), "owner_email": owner, "claimed": bool(owner),
                     "published_at": r.get("published_at") or ""})
    return Snapshot(rows=rows, by_handle={r["handle"]: r for r in rows if r.get("handle")}, loaded_at=time.monotonic())


def snapshot() -> Snapshot | None:
    """The published cards, at most SNAPSHOT_TTL_SECONDS old; None when there are too many to copy
    or the database could not be read (search then reads it the old way). The load holds the lock, so
    a write that lands during it waits in invalidate() and clears the copy right after."""
    global _snapshot, _too_big_at
    now = time.monotonic()
    with _lock:
        if _snapshot is not None and now - _snapshot.loaded_at < SNAPSHOT_TTL_SECONDS:
            return _snapshot
        if _too_big_at is not None and now - _too_big_at < SNAPSHOT_TTL_SECONDS:
            return None
        try:
            loaded = _load()
        except Exception as exc:  # noqa: BLE001 — no copy: search falls back to the database
            logger.warning("card snapshot unavailable (%s); searching the database", exc)
            return None
        if loaded is None:
            _too_big_at, _snapshot = now, None
            return None
        _too_big_at, _snapshot = None, loaded
        return loaded


def published_card(snap: Snapshot | None, handle: str):
    """The published card for a handle from the snapshot, or None (then ask the database: it also
    follows renamed handles)."""
    row = snap.by_handle.get(handle) if snap and handle else None
    return row["model"] if row else None


def claimed_for(snap: Snapshot | None, handles: list[str]) -> dict[str, bool] | None:
    """handle -> claimed for every handle, or None when the snapshot does not know them all."""
    if snap is None or any(h not in snap.by_handle for h in handles):
        return None
    return {h: snap.by_handle[h]["claimed"] for h in handles}


def invalidate() -> None:
    """A card was written: the next search reads the database again."""
    global _snapshot, _too_big_at
    with _lock:
        _snapshot, _too_big_at = None, None
