-- Migration: github_profiles
--
-- Cached snapshot of a user's GitHub repositories, languages and
-- derived skills/projects, refreshed daily by backend/services/github_sync.py.
-- Mirrors the linkedin_profiles pattern: raw data lands here, the memory
-- layer gets derived facts, and this table is the diff base so daily
-- syncs only declare new facts.
--
-- See backend/services/github_sync.py and backend/agent/github_sync_loop.py
-- for the write path.

CREATE TABLE IF NOT EXISTS github_profiles (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username    TEXT,
    raw_repos   JSONB NOT NULL DEFAULT '[]'::jsonb,
    skills      JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects    JSONB NOT NULL DEFAULT '[]'::jsonb,
    synced_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS github_profiles_synced_at_idx
    ON github_profiles (synced_at DESC);

ALTER TABLE github_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own github profile" ON github_profiles
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users delete own github profile" ON github_profiles
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on github_profiles" ON github_profiles
    FOR ALL USING (auth.role() = 'service_role');
