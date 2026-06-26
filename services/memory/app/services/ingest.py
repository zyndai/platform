"""Shared ingestion core (brief §7.2): turn the user's conversation turns into
trace_chunks and enqueue async embedding/extraction.

Used by both the HTTP /ingest endpoint (ChatGPT plugin, brief §7) and the MCP
`remember` tool (Claude and other MCP clients) so every source writes to the graph
the same way. Stays fast: auth + dedup + INSERT + enqueue only — no heavy work here.
"""
import hashlib
import re

import asyncpg

from app.models import Turn

# brief §7.2 — turns shorter than this carry no extractable signal. The MCP `remember`
# tool lowers it because those writes are intentional single facts, not chat noise.
MIN_CHUNK_CHARS = 40

# C0 control chars except tab/newline/CR. Postgres text columns reject NUL outright
# (raises at INSERT), and other controls are noise — strip before storing/embedding.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(text: str) -> str:
    """Strip text-illegal control characters (incl. NUL) so ingestion can't 500."""
    return _CONTROL_RE.sub("", text or "")


async def ingest_turns(
    pool: asyncpg.Pool,
    arq,
    user_id: str,
    source_system: str,
    turns: list[Turn],
    conversation_id: str | None = None,
    min_chars: int = MIN_CHUNK_CHARS,
) -> tuple[int, int]:
    """Insert new user-turn chunks and enqueue them for processing.

    Returns (inserted, skipped). Only user turns count; assistant turns, sub-threshold
    turns, and duplicates (per content hash) are skipped. Caller supplies the arq pool
    so this works from the API process and the MCP process alike.
    """
    # Self-heal: a validly-signed token whose user row was removed is re-provisioned so
    # ingestion never 500s on a missing FK.
    await pool.execute(
        "INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        user_id, f"user-{user_id}@zynd.local",
    )

    inserted = 0
    skipped = 0
    for index, turn in enumerate(turns):
        if turn.role != "user":  # only user content carries signal (§14.6)
            continue
        text = clean_text(turn.content).strip()
        if len(text) < min_chars:
            skipped += 1
            continue

        content_hash = hashlib.sha256(f"{user_id}:{text}".encode()).hexdigest()
        row = await pool.fetchrow(
            """INSERT INTO trace_chunks
                 (user_id, source_system, raw_text, conversation_id,
                  turn_start, turn_end, content_hash, observed_at)
               VALUES ($1, $2, $3, $4, $5, $5, $6, $7)
               ON CONFLICT (user_id, content_hash) DO NOTHING
               RETURNING id""",
            user_id, source_system, text, conversation_id,
            index, content_hash, turn.timestamp,
        )
        if row is None:
            skipped += 1
            continue

        # Durability: the chunk is committed, but if the enqueue fails (e.g. Redis
        # down) it would never be processed AND its content_hash would block re-ingest
        # forever. Roll the chunk back and surface the error so the caller can retry.
        try:
            await arq.enqueue_job("chunk_processor", str(row["id"]))
        except Exception:
            await pool.execute("DELETE FROM trace_chunks WHERE id = $1", row["id"])
            raise
        inserted += 1

    await pool.execute("UPDATE users SET last_active_at = now() WHERE id = $1", user_id)
    return inserted, skipped
