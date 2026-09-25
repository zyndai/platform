-- Additive: persist the per-turn action summary on chat_messages so the
-- frontend can rehydrate the ✅/⏳/⚠ status chips after a reload instead of
-- losing them (previously action_summary existed only in the SSE done event).
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS action_summary JSONB DEFAULT '[]'::jsonb;