-- ================================================================
-- Patch: split dm_threads.mode into per-side modes
--
-- The old `mode` column was a single shared flag, so flipping it on
-- one side silently flipped it on the other. That made mixed-mode
-- conversations ("me manual, them AI") impossible.
--
-- Replace with two columns:
--   initiator_mode — the mode of whoever the thread's initiator is
--   receiver_mode  — the mode of whoever the thread's receiver is
--
-- Each side flips ONLY their own column. The receiving webhook
-- handler decides whether to auto-reply by comparing the receiving
-- user's agent_id against initiator_id / receiver_id and checking
-- the matching column.
--
-- We keep `mode` around temporarily (nullable) for safety — nothing
-- reads it after the backend changes land, and it can be dropped
-- later once you're confident.
-- ================================================================

ALTER TABLE dm_threads
    ADD COLUMN IF NOT EXISTS initiator_mode TEXT NOT NULL DEFAULT 'agent'
    CHECK (initiator_mode IN ('human', 'agent'));

ALTER TABLE dm_threads
    ADD COLUMN IF NOT EXISTS receiver_mode TEXT NOT NULL DEFAULT 'agent'
    CHECK (receiver_mode IN ('human', 'agent'));

-- Backfill from the old single column so existing rows get sensible defaults.
UPDATE dm_threads
SET initiator_mode = COALESCE(mode, 'agent'),
    receiver_mode  = COALESCE(mode, 'agent')
WHERE mode IS NOT NULL;
