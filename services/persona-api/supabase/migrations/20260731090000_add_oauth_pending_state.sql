-- Patch: persist OAuth `state` across the authorize -> callback round-trip.
--
-- Previously this lived in an in-memory dict in oauth_routes.py. The `api`
-- PM2 process restarts frequently (crash loop, memory limit, deploys), which
-- wipes that dict — any OAuth flow whose provider consent screen is still
-- open when a restart happens comes back to "Invalid or expired state" even
-- though the user did everything right. Moving it to Supabase makes it
-- survive process restarts.

CREATE TABLE IF NOT EXISTS oauth_pending_state (
    state         TEXT PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,
    code_verifier TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    -- Google/LinkedIn/etc consent screens shouldn't reasonably take longer
    -- than this; also bounds how long an abandoned row lingers.
    expires_at    TIMESTAMPTZ DEFAULT (now() + interval '15 minutes')
);

-- Only the backend's service-role client touches this table (no direct
-- user access needed), so RLS is enabled with no public policies.
ALTER TABLE oauth_pending_state ENABLE ROW LEVEL SECURITY;
