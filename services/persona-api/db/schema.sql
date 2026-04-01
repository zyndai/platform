-- ================================================================
-- Zynd AI — Database Schema
-- Run this in the Supabase SQL Editor (http://127.0.0.1:54323)
-- ================================================================

-- API tokens table — stores scoped OAuth access/refresh tokens
-- for each provider (LinkedIn, Twitter, Google) per user.
-- These are NOT the Supabase auth tokens — they're the API tokens
-- needed to call platform APIs on the user's behalf.
CREATE TABLE IF NOT EXISTS api_tokens (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,          -- 'linkedin', 'twitter', 'google'
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    expires_at    TIMESTAMPTZ,
    scopes        TEXT,                   -- space-separated scopes
    raw_data      JSONB DEFAULT '{}'::jsonb,  -- full token response for debugging
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, provider)
);

-- Row Level Security — users can only see their own tokens
ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own tokens"
    ON api_tokens FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own tokens"
    ON api_tokens FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own tokens"
    ON api_tokens FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own tokens"
    ON api_tokens FOR DELETE
    USING (auth.uid() = user_id);

-- Service role bypass — backend can access all tokens
CREATE POLICY "Service role full access"
    ON api_tokens FOR ALL
    USING (auth.role() = 'service_role');

-- Chat messages table (for future persistence)
CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,         -- 'user', 'assistant'
    content         TEXT NOT NULL,
    actions         JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own messages"
    ON chat_messages FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on messages"
    ON chat_messages FOR ALL
    USING (auth.role() = 'service_role');
