-- ================================================================
-- Patch: enriched_contacts / enriched_companies
--
-- Local cache of records returned by QuickEnrich (the contact &
-- company database behind the persona's people-discovery tools).
--
-- Two jobs:
--   1. Cost. Email/phone reveals and company-finder results cost
--      credits per record. A repeat lookup of the same person or
--      company inside the TTL window is served from here for free.
--   2. Recall. Someone the persona found last week stays
--      referenceable ("email that founder I found") instead of
--      vanishing when the conversation scrolls out of context.
--
-- We cache RECORDS, not queries. Every endpoint upserts what it
-- returns; only the deterministic key-based person lookups
-- (email / phone / reverse-email) read the cache and skip the API
-- call, because only those are genuinely equivalent to a fresh call.
--
-- Rows are scoped per user: the same person looked up by two users
-- costs two credits, which is the right trade for clean RLS and a
-- straightforward "delete my data" story.
-- ================================================================

CREATE TABLE IF NOT EXISTS enriched_contacts (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Normalized identity key: 'li:<linkedin path>', 'em:<email>', or
    -- 'nc:<company host>|<first>|<last>'. See services/quickenrich_cache.py.
    cache_key          TEXT NOT NULL,
    employee_linkedin  TEXT,
    email              TEXT,
    first_name         TEXT,
    last_name          TEXT,
    title              TEXT,
    company_name       TEXT,
    company_url        TEXT,
    phone              TEXT,
    phone_type         TEXT,
    has_email          BOOLEAN DEFAULT FALSE,
    has_phone          BOOLEAN DEFAULT FALSE,
    -- Full record as returned, so new fields survive without a migration.
    data               JSONB DEFAULT '{}'::jsonb,
    -- Which endpoint produced this row (contact-finder, employee-search, ...).
    source             TEXT,
    -- When contact details were last actually paid for. NULL means this row
    -- came from a free discovery call and carries no email/phone yet.
    enriched_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, cache_key)
);

CREATE INDEX IF NOT EXISTS enriched_contacts_user_linkedin_idx
    ON enriched_contacts (user_id, employee_linkedin);
CREATE INDEX IF NOT EXISTS enriched_contacts_user_email_idx
    ON enriched_contacts (user_id, email);
CREATE INDEX IF NOT EXISTS enriched_contacts_user_created_idx
    ON enriched_contacts (user_id, created_at DESC);

ALTER TABLE enriched_contacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can CRUD own enriched contacts" ON enriched_contacts;
CREATE POLICY "Users can CRUD own enriched contacts"
    ON enriched_contacts FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role full access on enriched_contacts" ON enriched_contacts;
CREATE POLICY "Service role full access on enriched_contacts"
    ON enriched_contacts FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');


-- ── Companies ───────────────────────────────────────────────────
-- company-finder charges 1 credit per company RETURNED, which makes
-- it the priciest endpoint and the one most worth not re-fetching.

CREATE TABLE IF NOT EXISTS enriched_companies (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Normalized domain, e.g. 'acme.com'.
    cache_key          TEXT NOT NULL,
    company_name       TEXT,
    company_url        TEXT,
    linkedin_url       TEXT,
    industry           TEXT,
    employee_count     TEXT,
    revenue            TEXT,
    city               TEXT,
    region_code        TEXT,
    country_code       TEXT,
    data               JSONB DEFAULT '{}'::jsonb,
    source             TEXT,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, cache_key)
);

CREATE INDEX IF NOT EXISTS enriched_companies_user_created_idx
    ON enriched_companies (user_id, created_at DESC);

ALTER TABLE enriched_companies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can CRUD own enriched companies" ON enriched_companies;
CREATE POLICY "Users can CRUD own enriched companies"
    ON enriched_companies FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role full access on enriched_companies" ON enriched_companies;
CREATE POLICY "Service role full access on enriched_companies"
    ON enriched_companies FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
