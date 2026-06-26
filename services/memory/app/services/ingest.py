"""Shared ingestion core (brief §7.2): turn the user's conversation turns into
trace_chunks and enqueue async embedding/extraction.

Used by both the HTTP /ingest endpoint (ChatGPT plugin, brief §7) and the MCP
`remember` tool (Claude and other MCP clients) so every source writes to the graph
the same way. Stays fast: auth + dedup + INSERT + enqueue only — no heavy work here.
"""
import hashlib

import asyncpg

from app.models import Turn

# brief §7.2 — turns shorter than this carry no extractable signal. The MCP `remember`
# tool lowers it because those writes are intentional single facts, not chat noise.
MIN_CHUNK_CHARS = 40


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
        text = turn.content.strip()
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

        inserted += 1
        await arq.enqueue_job("chunk_processor", str(row["id"]))

    await pool.execute("UPDATE users SET last_active_at = now() WHERE id = $1", user_id)
    return inserted, skipped
