-- Additive: persist the per-turn action summary on chat_messages (see
-- backend/db/patch_add_action_summary.sql). Mirrored here so the Supabase
-- migrations directory stays a complete history.
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS action_summary JSONB DEFAULT '[]'::jsonb;