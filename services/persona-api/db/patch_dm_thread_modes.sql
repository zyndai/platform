-- ================================================================
-- Patch: thread mode + per-message sender attribution
--
-- Adds two columns that separate "AI is handling this thread" from
-- "humans are talking directly":
--
--   dm_threads.mode
--     'human' (default)  → inbound messages are NOT auto-replied;
--                          they sit in the inbox for the human to answer.
--     'agent'            → inbound messages are run through the
--                          orchestrator and auto-replied (the legacy
--                          behavior). Used when the AI initiated the
--                          thread or the user explicitly delegated.
--
--   dm_messages.sender_type
--     'human' (default)  → typed by the user in MessagesPanel.
--     'agent'            → produced by the orchestrator (ours or theirs).
--     'system'           → reserved for status notices.
--
-- Existing rows get the defaults, which preserves the current UX for
-- threads that were already in the database. New threads created via
-- the MessagesPanel UI default to 'human'; new threads created by the
-- AI tools (request_connection / message_zynd_agent) override to
-- 'agent' so the AI can keep the conversation going on its own.
-- ================================================================

ALTER TABLE dm_threads
    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'human'
    CHECK (mode IN ('human', 'agent'));

ALTER TABLE dm_messages
    ADD COLUMN IF NOT EXISTS sender_type TEXT NOT NULL DEFAULT 'human'
    CHECK (sender_type IN ('human', 'agent', 'system'));
