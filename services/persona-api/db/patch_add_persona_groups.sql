-- Patch: persona_groups + membership + messages
--
-- Persona Groups are bounded chat rooms shared by 3–15 personas. MVP is a
-- Slack-lite: humans post into a room, only members can read/post, and
-- non-members never see the group exists (404, not 403, so the id space
-- is un-fingerprintable — same defense used on /api/persona/{id}/public).
--
-- Phase 2 (proactive personas) lands without a migration: the `permissions`
-- column on persona_group_members already carries the per-member toggles
-- and persona_group_messages.channel already supports 'agent' / 'broadcast'
-- rows the dispatcher will write into later.
--
-- group_seed_index gives each group a derivable keypair (off the developer
-- seed via HKDF, same pattern as persona_manager._derive_agent_keypair).
-- The keypair signs A2A v3 envelopes carrying the `group_context` claim a
-- receiver validates before honoring cross-persona queries inside the group.

-- ── Groups ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS persona_groups (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug              TEXT UNIQUE NOT NULL,
    name              TEXT NOT NULL,
    description       TEXT,
    avatar_url        TEXT,
    owner_user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    visibility        TEXT NOT NULL DEFAULT 'private'
                      CHECK (visibility IN ('private', 'open')),
    invite_token      TEXT UNIQUE,
    group_seed_index  INTEGER NOT NULL DEFAULT 0,
    archived_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS persona_groups_owner_idx
    ON persona_groups (owner_user_id);

-- ── Members ─────────────────────────────────────────────────────────────
-- agent_id is denormalized from persona_agents so realtime filters on a
-- group's roster don't need a join from the client; the API keeps it in
-- sync when a member's persona is (re)deployed.
CREATE TABLE IF NOT EXISTS persona_group_members (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id      UUID NOT NULL REFERENCES persona_groups(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    agent_id      TEXT,
    role          TEXT NOT NULL DEFAULT 'member'
                  CHECK (role IN ('owner', 'admin', 'member')),
    permissions   JSONB NOT NULL DEFAULT jsonb_build_object(
                      'can_see_brief',       false,
                      'can_query_calendar',  false,
                      'can_post',            true,
                      'can_invite',          false,
                      'can_speak_for_group', false
                  ),
    invited_by    UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (group_id, user_id)
);

CREATE INDEX IF NOT EXISTS persona_group_members_user_idx
    ON persona_group_members (user_id);
CREATE INDEX IF NOT EXISTS persona_group_members_agent_idx
    ON persona_group_members (agent_id);

-- ── Messages ────────────────────────────────────────────────────────────
-- sender_user_id is set for human posts; sender_agent_id is set for any
-- post originating from a persona (phase 2). Either one or both may be
-- present — an agent posting "on behalf of" its principal carries both
-- so the UI can render attribution either way.
CREATE TABLE IF NOT EXISTS persona_group_messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id         UUID NOT NULL REFERENCES persona_groups(id) ON DELETE CASCADE,
    sender_user_id   UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    sender_agent_id  TEXT,
    sender_name      TEXT,
    channel          TEXT NOT NULL DEFAULT 'human'
                     CHECK (channel IN ('human', 'agent', 'system', 'broadcast')),
    content          TEXT NOT NULL,
    reply_to         UUID REFERENCES persona_group_messages(id) ON DELETE SET NULL,
    metadata         JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS persona_group_messages_group_idx
    ON persona_group_messages (group_id, created_at DESC);

-- ── RLS ─────────────────────────────────────────────────────────────────
-- The backend uses the service-role key for all writes and filters by
-- membership in Python, so RLS here is a defense-in-depth layer for any
-- direct frontend reads (notably the realtime channel subscription on
-- persona_group_messages). The membership check is a single subquery,
-- which Postgres planner handles cheaply for the table sizes we expect.
ALTER TABLE persona_groups        ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_group_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "members read group" ON persona_groups
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM persona_group_members m
             WHERE m.group_id = persona_groups.id AND m.user_id = auth.uid()
        )
    );

CREATE POLICY "members read roster" ON persona_group_members
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM persona_group_members m
             WHERE m.group_id = persona_group_members.group_id AND m.user_id = auth.uid()
        )
    );

CREATE POLICY "members read messages" ON persona_group_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM persona_group_members m
             WHERE m.group_id = persona_group_messages.group_id AND m.user_id = auth.uid()
        )
    );

CREATE POLICY "service role full access on persona_groups" ON persona_groups
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service role full access on persona_group_members" ON persona_group_members
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service role full access on persona_group_messages" ON persona_group_messages
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
