"""Recent GitHub activity per person, for the feed, kept in memory and refreshed in the background.

The feed shows releases, new repositories and merged pull requests from the GitHub accounts linked
on cards. Reading them takes one GitHub call per person (about 0.3 s, and GitHub rate-limits), so a
feed request must never make those calls itself: it asks get() for what is cached and gets it at
once. Anything missing or older than GITHUB_TTL_SECONDS is queued for a small worker pool
(MAX_CONCURRENT_FETCHES threads) and shows up on a later request. A person's old result keeps
serving while the new one loads, the way card_cache.py does for cards, so an unreachable GitHub
costs freshness, not availability.

A failed read (rate limit, unknown user, network) is remembered for FAILURE_RETRY_SECONDS so one
bad handle is not retried on every request; it keeps the person's previous items, if any. Without
GITHUB_TOKEN GitHub allows only 60 calls an hour per address, so a cold start over many people fills
in over several hours: MAX_QUEUED_PER_CALL keeps one request from queueing the whole corpus at once.

The copy lives in this process only (cards-api runs one worker); a restart empties it and the next
requests refill it.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from scraping import github

logger = logging.getLogger(__name__)

GITHUB_TTL_SECONDS = 6 * 3600
FAILURE_RETRY_SECONDS = 30 * 60
MAX_CONCURRENT_FETCHES = 4
MAX_QUEUED_PER_CALL = 40


@dataclass
class _Entry:
    items: list[dict] = field(default_factory=list)
    checked_at: float = 0.0          # time.monotonic() of the last attempt
    ok: bool = False                 # whether that attempt read GitHub


_lock = threading.Lock()
_entries: dict[str, _Entry] = {}
_queued: set[str] = set()            # handles with a read queued or running
_pool: ThreadPoolExecutor | None = None


def _key(handle: str) -> str:
    return handle.lower()


def _fetch(handle: str) -> None:
    items = None
    try:
        items = github.fetch_notable_activity(handle)
    except Exception as exc:  # noqa: BLE001 — never let a refresh kill its thread
        logger.info("feed github: %s unavailable (%s)", handle, exc)
    with _lock:
        previous = _entries.get(_key(handle))
        _entries[_key(handle)] = _Entry(
            items=items if items is not None else (previous.items if previous else []),
            checked_at=time.monotonic(), ok=items is not None)
        _queued.discard(_key(handle))


def _is_stale(entry: _Entry | None, now: float) -> bool:
    if entry is None:
        return True
    return now - entry.checked_at >= (GITHUB_TTL_SECONDS if entry.ok else FAILURE_RETRY_SECONDS)


def get(handles: list[str]) -> dict[str, list[dict]]:
    """handle -> cached notable activity, for the handles that have any. Never waits on GitHub:
    handles that are missing or stale are queued and the old items (if any) are returned now."""
    global _pool
    now = time.monotonic()
    out: dict[str, list[dict]] = {}
    to_fetch: list[str] = []
    with _lock:
        for handle in dict.fromkeys(handles):
            entry = _entries.get(_key(handle))
            if entry and entry.items:
                out[handle] = list(entry.items)
            if _key(handle) not in _queued and _is_stale(entry, now) and len(to_fetch) < MAX_QUEUED_PER_CALL:
                _queued.add(_key(handle))
                to_fetch.append(handle)
        if to_fetch and _pool is None:
            _pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FETCHES, thread_name_prefix="feed-github")
        pool = _pool
    for handle in to_fetch:
        pool.submit(_fetch, handle)
    return out


def clear() -> None:
    """Forget everything (tests)."""
    with _lock:
        _entries.clear()
        _queued.clear()
