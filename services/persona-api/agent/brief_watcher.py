"""
Brief Watcher — polls each persona's Brief Google Doc for changes and
extracts any new todo items the principal added.

Runs as a single async task started in main.py's lifespan, alongside
the heartbeat manager. Pattern is deliberately the same: one task that
iterates all personas instead of one task per user.

Detection strategy (deterministic, no LLM cost):
  - For each persona with a `brief_doc_id`, ask Drive API for the doc's
    current `headRevisionId`.
  - If it differs from the `brief_doc_revision_id` we have stored,
    fetch the doc content and parse it for todo lines. Patterns we
    recognise: "- [ ] thing", "[ ] thing", "TODO: thing".
  - Insert any titles we haven't already stored as `brief_todos` rows
    for this user. Idempotent on title — re-extracting the same line
    won't create duplicates.
  - Update `brief_doc_revision_id` so we won't re-process this revision.

Removed lines: if the user deletes a "- [ ]" line from the doc, the
existing brief_todos row is LEFT ALONE. Two reasons:
  1. The user might have just been editing — deleting and re-adding.
  2. Marking it done automatically would be incorrect for the case
     where the user simply changed their mind.
The Todos tab UI lets the user toggle / delete manually.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterable

import config

logger = logging.getLogger(__name__)


# Default poll interval — every 5 minutes. Each cycle hits Drive API
# once per persona with a brief doc, so this is a tradeoff between
# responsiveness and Google API quota.
DEFAULT_POLL_INTERVAL_SECONDS = 300


# Lines we treat as todos. Order matters: bullet-with-checkbox first
# so the bare-checkbox pattern doesn't double-match it.
_TODO_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*[-*]\s*\[\s*\]\s*(.+)$", re.MULTILINE),
    re.compile(r"^\s*\[\s*\]\s*(.+)$", re.MULTILINE),
    re.compile(r"^\s*TODO:?\s*(.+)$", re.MULTILINE | re.IGNORECASE),
]


def extract_todo_titles(content: str) -> list[str]:
    """Return ordered, de-duplicated todo titles found in `content`."""
    out: list[str] = []
    seen: set[str] = set()
    for pat in _TODO_PATTERNS:
        for m in pat.finditer(content):
            title = m.group(1).strip()
            # Strip any trailing checkbox markers a second pattern would
            # match (e.g. "[ ] foo" inside a bullet that already matched).
            if not title or title in seen:
                continue
            seen.add(title)
            out.append(title)
    return out


class BriefWatcher:
    """Single async task that polls all personas with brief docs."""

    def __init__(self, poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS):
        self._poll_interval = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[brief_watcher] Started (poll every {self._poll_interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[brief_watcher] Stopped")

    async def _loop(self):
        # First pass runs immediately so dev-mode iteration is fast;
        # subsequent passes wait the full interval.
        while self._running:
            try:
                await asyncio.to_thread(self._poll_all)
            except Exception as e:
                logger.warning(f"[brief_watcher] Poll cycle failed: {e}")
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    # ── Sync helpers (run in a thread to keep the event loop free) ──

    def _supabase(self):
        from supabase import create_client
        return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

    def _poll_all(self):
        """One full sweep across every persona that has a brief doc."""
        sb = self._supabase()
        rows = (
            sb.table("persona_agents")
            .select("user_id,brief_doc_id,brief_doc_revision_id")
            .eq("active", True)
            .not_.is_("brief_doc_id", "null")
            .execute()
        )
        for row in rows.data or []:
            try:
                self._poll_one(sb, row)
            except Exception as e:
                logger.warning(
                    f"[brief_watcher] Poll failed for user {row.get('user_id')}: {e}"
                )

    def _poll_one(self, sb, row: dict):
        user_id = row["user_id"]
        doc_id = row["brief_doc_id"]
        last_revision = row.get("brief_doc_revision_id")

        from googleapiclient.discovery import build
        from mcp.tools.google.common import get_google_creds
        from mcp.tools.google.docs import read_document

        try:
            creds = get_google_creds(user_id)
        except ValueError:
            # User disconnected Google; nothing to poll.
            return

        drive = build("drive", "v3", credentials=creds)
        meta = drive.files().get(fileId=doc_id, fields="headRevisionId").execute()
        current_revision = meta.get("headRevisionId")
        if not current_revision:
            return
        if current_revision == last_revision:
            return  # No new edits since last poll.

        # Doc has changed — fetch full content and extract todos.
        fetched = read_document(user_id=user_id, document_id=doc_id)
        if not fetched.get("success"):
            logger.warning(
                f"[brief_watcher] read_document failed for {doc_id}: {fetched.get('error')}"
            )
            return

        titles = extract_todo_titles(fetched.get("content") or "")
        if titles:
            self._upsert_todos(sb, user_id, titles)

        sb.table("persona_agents").update({
            "brief_doc_revision_id": current_revision,
        }).eq("user_id", user_id).execute()
        logger.info(
            f"[brief_watcher] {user_id}: revision {last_revision} → {current_revision}, "
            f"{len(titles)} todo titles extracted"
        )

    def _upsert_todos(self, sb, user_id: str, titles: Iterable[str]):
        """
        Insert any todo titles we don't already have for this user.

        We only check against rows where done=false — a previously-completed
        todo with the same title is allowed to come back as a fresh open
        item (e.g. a recurring action the user re-added to the doc).
        """
        existing = (
            sb.table("brief_todos")
            .select("title")
            .eq("user_id", user_id)
            .eq("done", False)
            .execute()
        )
        existing_titles = {r["title"] for r in (existing.data or [])}
        new_rows = [
            {"user_id": user_id, "title": t, "source_text": t}
            for t in titles
            if t not in existing_titles
        ]
        if new_rows:
            sb.table("brief_todos").insert(new_rows).execute()


brief_watcher = BriefWatcher()
