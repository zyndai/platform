-- ================================================================
-- Patch: move Telegram state off disk and into the database
--
-- Two new tables:
--
--   telegram_links — chat_id ↔ user_id handshake map.
--     Replaces the old telegram_users.json file on disk, which
--     didn't survive container redeploys and had no concurrent
--     write safety.
--
--   telegram_chat_history — persistent per-chat conversation
--     history for the orchestrator. One row per conversation_id,
--     the full message list stored as JSONB so tool-call messages
--     and their intermediate context survive verbatim. Without
--     this, the backend's in-memory _conversations dict got wiped
--     on every restart, and the Telegram bot lost all memory of
--     prior turns.
--
-- Summarization / window capping comes later — for v1 we just
-- save and load everything.
-- ================================================================

CREATE TABLE IF NOT EXISTS telegram_links (
    user_id    UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    chat_id    TEXT NOT NULL UNIQUE,
    linked_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS telegram_links_chat_idx ON telegram_links (chat_id);

ALTER TABLE telegram_links ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own telegram link" ON telegram_links
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users delete own telegram link" ON telegram_links
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on telegram_links" ON telegram_links
    FOR ALL USING (auth.role() = 'service_role');


CREATE TABLE IF NOT EXISTS telegram_chat_history (
    conversation_id  TEXT PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    messages         JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS telegram_chat_history_user_idx ON telegram_chat_history (user_id);

ALTER TABLE telegram_chat_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own telegram history" ON telegram_chat_history
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on telegram_chat_history" ON telegram_chat_history
    FOR ALL USING (auth.role() = 'service_role');
