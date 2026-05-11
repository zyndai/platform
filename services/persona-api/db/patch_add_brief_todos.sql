-- Patch: brief_todos table
--
-- The brief watcher (backend/agent/brief_watcher.py) polls each persona's
-- Brief Google Doc on an interval. When it detects a new revision, it
-- diffs the content and asks an LLM to extract any new actionable items
-- the principal added — those are persisted here and surfaced in the
-- dashboard's Todos tab.
--
-- source_text holds the snippet of the doc that produced this todo, so
-- the user can trace a todo back to the line they wrote.
--
-- RLS: a user only ever sees their own todos. Service role (used by the
-- watcher to insert) bypasses RLS naturally.

CREATE TABLE IF NOT EXISTS brief_todos (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    source_text TEXT,
    done        BOOLEAN NOT NULL DEFAULT FALSE,
    done_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS brief_todos_user_idx
    ON brief_todos (user_id, done, created_at DESC);

ALTER TABLE brief_todos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own brief todos" ON brief_todos
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own brief todos" ON brief_todos
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own brief todos" ON brief_todos
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on brief_todos" ON brief_todos
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
