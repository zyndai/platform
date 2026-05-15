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
import json
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
#
# We use `[ \t]*` (not `\s*`) for in-line whitespace because `\s` also
# matches `\n`, which lets a pattern silently span multiple lines and
# capture the wrong content (e.g. a bullet with no body silently consumes
# the next line). Anchors `^` and `$` rely on re.MULTILINE.
_TODO_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^[ \t]*[-*][ \t]*\[[ \t]*\][ \t]*(.+?)[ \t]*$", re.MULTILINE),
    re.compile(r"^[ \t]*\[[ \t]*\][ \t]*(.+?)[ \t]*$", re.MULTILINE),
    re.compile(r"^[ \t]*TODO:?[ \t]*(.+?)[ \t]*$", re.MULTILINE | re.IGNORECASE),
]


def extract_todo_titles(content: str) -> list[str]:
    """Return ordered, de-duplicated todo titles found in `content`.

    Regex-only extractor — catches explicit `- [ ] X` / `[ ] X` / `TODO: X`
    lines. Used as the fallback when the LLM extractor fails. The
    primary extractor is `extract_todo_titles_llm` below.
    """
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


# Cap how much of the brief we send to the LLM. 6000 chars ≈ ~1500 tokens of
# content, plenty for almost any hand-written brief and bounded enough that
# a runaway doc can't blow up the prompt cost.
_LLM_BRIEF_CHAR_CAP = 6000

_LLM_TODO_SYSTEM = (
    "You extract actionable todo items from a user's personal 'brief' document. "
    "The brief is what THE USER wrote about themselves — what they're working "
    "on, who they want to meet, what they want to avoid. You return ONLY items "
    "that are clearly things they intend to do, follow up on, or want help "
    "with. Skip declarative statements about who they are, what they like, "
    "and background context. Skip opinions and meta-commentary. Skip section "
    "headings. Be conservative — it's better to return fewer high-quality "
    "todos than many low-quality ones. NEVER invent items the brief doesn't "
    "actually imply."
)


def _llm_todo_prompt(content: str) -> str:
    """User-message prompt for the extractor LLM call."""
    return (
        "Extract concrete todo items from this brief. Respond ONLY with a JSON "
        "object of the shape {\"todos\": [\"title 1\", \"title 2\", ...]}. Each "
        "title is a short imperative phrase, 3–12 words, like \"Email Sarah "
        "about the demo\" or \"Follow up with investor X\". If the brief contains "
        "no actionable items, respond with {\"todos\": []}. No prose, no "
        "explanation, no code fences — just the JSON.\n\nBrief:\n---\n"
        + content
        + "\n---"
    )


def extract_todo_titles_llm(content: str) -> list[str] | None:
    """Run the configured LLM to extract todos from the brief.

    Returns the title list on success, or None on any failure (network,
    timeout, malformed JSON, empty/garbage response). Callers should fall
    back to ``extract_todo_titles`` (regex) on None — that way the watcher
    keeps working when the LLM is unavailable.
    """
    snippet = (content or "").strip()
    if not snippet:
        return []
    if len(snippet) > _LLM_BRIEF_CHAR_CAP:
        snippet = snippet[:_LLM_BRIEF_CHAR_CAP]

    try:
        # Lazy import — orchestrator pulls in the LLM SDKs which are slow to
        # initialize, and the watcher's import path runs at app startup.
        from agent.orchestrator import _get_provider, strip_think_tags
        provider = _get_provider()
        messages = [
            {"role": "system", "content": _LLM_TODO_SYSTEM},
            {"role": "user", "content": _llm_todo_prompt(snippet)},
        ]
        # No tools — pure text reply. Returns (text, tool_calls) where the
        # second is None when tools is empty.
        text, _ = provider.chat_with_tools(messages, tools=[])
        text = strip_think_tags(text or "").strip()
        if not text:
            return None

        # Models sometimes still wrap in ``` code fences or prepend chatter
        # despite the instruction. Pull out the first JSON object we see.
        import re as _re
        match = _re.search(r"\{.*\}", text, _re.DOTALL)
        if not match:
            return None
        parsed = json.loads(match.group(0))
        raw_titles = parsed.get("todos")
        if not isinstance(raw_titles, list):
            return None

        out: list[str] = []
        seen: set[str] = set()
        for t in raw_titles:
            if not isinstance(t, str):
                continue
            title = t.strip()
            if not title or title in seen:
                continue
            # Sanity cap to keep DB rows reasonable in length.
            if len(title) > 200:
                title = title[:200].rstrip()
            seen.add(title)
            out.append(title)
        return out
    except json.JSONDecodeError as e:
        logger.warning(f"[brief_watcher] LLM returned non-JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"[brief_watcher] LLM extraction failed: {e}")
        return None


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
        return config.get_supabase()

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

        # LLM-first extraction. The LLM catches implicit todos the regex
        # would miss ("I need to follow up with Sarah" → "Follow up with
        # Sarah"). If the LLM call fails or returns malformed output we
        # fall back to the regex extractor so a transient LLM error
        # doesn't silently drop a polling cycle.
        content = fetched.get("content") or ""
        llm_titles = extract_todo_titles_llm(content)
        if llm_titles is None:
            titles = extract_todo_titles(content)
            extractor = "regex_fallback"
        else:
            titles = llm_titles
            extractor = "llm"
        if titles:
            self._upsert_todos(sb, user_id, titles)

        sb.table("persona_agents").update({
            "brief_doc_revision_id": current_revision,
        }).eq("user_id", user_id).execute()
        logger.info(
            f"[brief_watcher] {user_id}: revision {last_revision} → {current_revision}, "
            f"{len(titles)} todos via {extractor}"
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
