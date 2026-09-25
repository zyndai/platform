-- Additive: cached X/Twitter scrape per user (see backend/db/schema.sql
-- §10c). Written by services/twitter_scraper.py via the service role;
-- read/delete via RLS by the owning user (Settings → Accounts card).
CREATE TABLE IF NOT EXISTS twitter_profiles (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    handle      TEXT,
    scraped_at  TIMESTAMPTZ,
    raw_tweets  JSONB NOT NULL DEFAULT '[]'::jsonb,
    facts       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS twitter_profiles_scraped_at_idx
    ON twitter_profiles (scraped_at DESC);

ALTER TABLE twitter_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own twitter profile" ON twitter_profiles
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users delete own twitter profile" ON twitter_profiles
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on twitter_profiles" ON twitter_profiles
    FOR ALL USING (auth.role() = 'service_role');
