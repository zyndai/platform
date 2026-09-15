-- ================================================================
-- Patch: suggested_contacts / suggested_contact_runs
--
-- Proactive "Similar people" suggestions for the People page.
-- Unlike enriched_contacts (a cache of records QuickEnrich has ever
-- returned for a user), this table is the *curated shortlist* the
-- system picked for a user's profile — grouped by which recipe found
-- them (same_role / same_company / near_you / shared_interests) with
-- a one-line reason, ranked, and regenerated on refresh.
--
-- Person data itself is NOT duplicated here — cache_key points at the
-- row in enriched_contacts (same user_id + cache_key), which already
-- holds the full record from services/quickenrich_cache.py. This table
-- only tracks *why* and *how well* a person matched.
-- ================================================================

CREATE TABLE IF NOT EXISTS suggested_contacts (
    id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Matches enriched_contacts.cache_key for the same user — see
    -- services/quickenrich_cache.py:contact_key().
    cache_key      TEXT NOT NULL,
    -- Which recipe surfaced this person: same_role | same_company |
    -- near_you | shared_interests. See services/people_suggestions.py.
    recipe         TEXT NOT NULL,
    -- One-line "why" shown on the card, e.g. "CTOs in Bangalore, like you".
    reason         TEXT,
    score          REAL DEFAULT 0,
    rank           INTEGER DEFAULT 0,
    generated_at   TIMESTAMPTZ DEFAULT now(),
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, cache_key, recipe)
);

CREATE INDEX IF NOT EXISTS suggested_contacts_user_rank_idx
    ON suggested_contacts (user_id, recipe, rank);

ALTER TABLE suggested_contacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can CRUD own suggested contacts" ON suggested_contacts;
CREATE POLICY "Users can CRUD own suggested contacts"
    ON suggested_contacts FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role full access on suggested_contacts" ON suggested_contacts;
CREATE POLICY "Service role full access on suggested_contacts"
    ON suggested_contacts FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');


-- ── Run bookkeeping ─────────────────────────────────────────────
-- One row per user. Drives the weekly refresh loop (skip anyone run
-- inside the last 7 days) and the manual "Refresh suggestions"
-- button's cooldown (skip anyone manually run inside the last hour).

CREATE TABLE IF NOT EXISTS suggested_contact_runs (
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    last_run_at    TIMESTAMPTZ,
    last_manual_at TIMESTAMPTZ,
    status         TEXT,   -- ok | error | skipped (not configured / no signals)
    detail         TEXT,
    updated_at     TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE suggested_contact_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own suggestion run state" ON suggested_contact_runs;
CREATE POLICY "Users can read own suggestion run state"
    ON suggested_contact_runs FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role full access on suggested_contact_runs" ON suggested_contact_runs;
CREATE POLICY "Service role full access on suggested_contact_runs"
    ON suggested_contact_runs FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
