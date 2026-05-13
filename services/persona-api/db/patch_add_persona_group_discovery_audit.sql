-- Patch: discovery + audit (phase 5)
--
-- Three additions, packaged together because they all serve the same
-- "groups become real social objects" story:
--
--   1. persona_groups.join_domain
--      Optional email-domain rule (e.g. "acme.com"). When a user with
--      a matching auth.users.email visits /dashboard/groups, an
--      "auto-join" CTA appears. Only meaningful for visibility='open'
--      groups; the API enforces that at write time.
--
--   2. persona_group_audit_events
--      One-row-per-access log of privacy-sensitive operations the
--      dispatcher performs on a member's data inside a group:
--        - brief_shared     (target's brief content sent to an asker's
--                            dispatch prompt)
--        - calendar_queried (target's freebusy read by an availability
--                            check or meeting-create call)
--      affected_user_id is the OWNER of the data (the "target"); the
--      `actor_user_id` is who triggered the read. The Activity panel
--      surfaces these to the affected user so they can see who's been
--      looking at what.
--
-- We deliberately don't log every chat read — too noisy, too low-value.
-- The events here are the ones a thoughtful user would actually want a
-- receipt for.

ALTER TABLE persona_groups
    ADD COLUMN IF NOT EXISTS join_domain TEXT;

CREATE INDEX IF NOT EXISTS persona_groups_join_domain_idx
    ON persona_groups (join_domain)
    WHERE join_domain IS NOT NULL AND archived_at IS NULL;

CREATE TABLE IF NOT EXISTS persona_group_audit_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id          UUID NOT NULL REFERENCES persona_groups(id) ON DELETE CASCADE,
    affected_user_id  UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    actor_user_id     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('brief_shared', 'calendar_queried')),
    metadata          JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS persona_group_audit_events_affected_idx
    ON persona_group_audit_events (affected_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS persona_group_audit_events_group_idx
    ON persona_group_audit_events (group_id, created_at DESC);

ALTER TABLE persona_group_audit_events ENABLE ROW LEVEL SECURITY;

-- Affected users read their own receipts.
CREATE POLICY "affected user reads own audit events"
    ON persona_group_audit_events
    FOR SELECT USING (auth.uid() = affected_user_id);

-- Group owners/admins read the full feed for their group (for moderation
-- visibility). Service role bypasses RLS for the API write path.
CREATE POLICY "owner reads group audit events"
    ON persona_group_audit_events
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM persona_group_members m
             WHERE m.group_id = persona_group_audit_events.group_id
               AND m.user_id = auth.uid()
               AND m.role IN ('owner', 'admin')
        )
    );

CREATE POLICY "service role full access on persona_group_audit_events"
    ON persona_group_audit_events
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
