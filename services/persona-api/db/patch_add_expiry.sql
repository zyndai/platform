-- Patch: add expires_at to published_pages for anonymous/TTL pages.
-- Anonymous pages (user_id = 00000000-0000-0000-0000-000000000000) expire.
-- Authenticated pages have expires_at = NULL (permanent).
-- Dropping FK on user_id so anonymous UUIDs don't need auth.users rows.

ALTER TABLE published_pages DROP CONSTRAINT IF EXISTS published_pages_user_id_fkey;
ALTER TABLE published_pages ADD COLUMN IF NOT EXISTS expires_at timestamptz;
CREATE INDEX IF NOT EXISTS published_pages_expires_idx
    ON published_pages (expires_at) WHERE expires_at IS NOT NULL;
