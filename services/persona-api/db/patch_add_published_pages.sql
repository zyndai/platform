-- ================================================================
-- Patch: published_pages
-- Shareable HTML / Markdown pages created by the agent on behalf of
-- the user. Slugs are unguessable tokens used in public share links.
-- ================================================================

CREATE TABLE IF NOT EXISTS published_pages (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    slug        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL CHECK (format IN ('html','markdown')),
    content     TEXT NOT NULL,
    visibility  TEXT NOT NULL DEFAULT 'unlisted'
                  CHECK (visibility IN ('public','unlisted','private')),
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS published_pages_slug_idx ON published_pages (slug);
CREATE INDEX IF NOT EXISTS published_pages_user_idx ON published_pages (user_id, created_at DESC);

ALTER TABLE published_pages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can CRUD own pages"
    ON published_pages FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Public read for public pages"
    ON published_pages FOR SELECT
    USING (visibility = 'public');

CREATE POLICY "Service role full access on published_pages"
    ON published_pages FOR ALL
    USING (auth.role() = 'service_role');
