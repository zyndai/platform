-- ================================================================
-- Zynd AI — Migration from v1 (DID/PolygonID) to v2 (Ed25519/agdns)
-- Run this in the Supabase SQL Editor to migrate an existing database.
--
-- This script:
--   1. Drops the old persona_dids table
--   2. Truncates dm_threads and dm_messages (fresh start for DMs)
--   3. Drops old RLS policies
--   4. Creates the new persona_agents table
--   5. Recreates dm_threads and dm_messages with updated RLS
-- ================================================================

-- ── Step 1: Drop old persona_dids table ──
DROP TABLE IF EXISTS persona_dids CASCADE;

-- ── Step 2: Clean up DMs (fresh start) ──
TRUNCATE dm_messages CASCADE;
TRUNCATE dm_threads CASCADE;

-- ── Step 3: Drop old RLS policies on dm_threads ──
DROP POLICY IF EXISTS "Users can read own threads" ON dm_threads;
DROP POLICY IF EXISTS "Users can start threads" ON dm_threads;
DROP POLICY IF EXISTS "Receiver can accept or block threads" ON dm_threads;

-- ── Step 4: Drop old RLS policies on dm_messages ──
DROP POLICY IF EXISTS "Users can read messages in non-blocked threads" ON dm_messages;
DROP POLICY IF EXISTS "Users can send messages in non-blocked threads" ON dm_messages;

-- ── Step 5: Add name columns to dm_threads if missing ──
ALTER TABLE dm_threads ADD COLUMN IF NOT EXISTS initiator_name TEXT DEFAULT '';
ALTER TABLE dm_threads ADD COLUMN IF NOT EXISTS receiver_name TEXT DEFAULT '';

-- ── Step 6: Create the new persona_agents table ──
CREATE TABLE IF NOT EXISTS persona_agents (
    user_id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    agent_id          TEXT NOT NULL UNIQUE,
    derivation_index  INTEGER NOT NULL UNIQUE,
    public_key        TEXT NOT NULL,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    capabilities      JSONB DEFAULT '[]'::jsonb,
    profile           JSONB DEFAULT '{}'::jsonb,
    webhook_url       TEXT,
    active            BOOLEAN DEFAULT true,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE persona_agents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own persona" ON persona_agents
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own persona" ON persona_agents
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Public read persona agents" ON persona_agents
    FOR SELECT USING (true);

CREATE POLICY "Service role full access on persona_agents" ON persona_agents
    FOR ALL USING (auth.role() = 'service_role');

-- ── Step 7: Recreate RLS policies on dm_threads using persona_agents ──
CREATE POLICY "Users can read own threads" ON dm_threads
    FOR SELECT USING (
        auth.uid()::text = initiator_id
        OR auth.uid()::text = receiver_id
        OR EXISTS (SELECT 1 FROM persona_agents WHERE user_id = auth.uid() AND (agent_id = initiator_id OR agent_id = receiver_id))
    );

CREATE POLICY "Users can start threads" ON dm_threads
    FOR INSERT WITH CHECK (
        auth.uid()::text = initiator_id
        OR EXISTS (SELECT 1 FROM persona_agents WHERE user_id = auth.uid() AND agent_id = initiator_id)
    );

CREATE POLICY "Receiver can accept or block threads" ON dm_threads
    FOR UPDATE USING (
        auth.uid()::text = receiver_id
        OR EXISTS (SELECT 1 FROM persona_agents WHERE user_id = auth.uid() AND agent_id = receiver_id)
    );

CREATE POLICY "Service role full access on dm_threads" ON dm_threads
    FOR ALL USING (auth.role() = 'service_role');

-- ── Step 8: Recreate RLS policies on dm_messages using persona_agents ──
CREATE POLICY "Users can read messages in non-blocked threads" ON dm_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM dm_threads t
            WHERE t.id = dm_messages.thread_id
              AND (
                  t.initiator_id = auth.uid()::text OR t.receiver_id = auth.uid()::text
                  OR EXISTS (SELECT 1 FROM persona_agents p WHERE p.user_id = auth.uid() AND (p.agent_id = t.initiator_id OR p.agent_id = t.receiver_id))
              )
              AND t.status != 'blocked'
        )
    );

CREATE POLICY "Users can send messages in non-blocked threads" ON dm_messages
    FOR INSERT WITH CHECK (
        (auth.uid()::text = sender_id OR EXISTS(SELECT 1 FROM persona_agents WHERE user_id = auth.uid() AND agent_id = sender_id))
        AND
        EXISTS (
            SELECT 1 FROM dm_threads t
            WHERE t.id = dm_messages.thread_id
              AND (
                  t.initiator_id = auth.uid()::text OR t.receiver_id = auth.uid()::text
                  OR EXISTS (SELECT 1 FROM persona_agents p WHERE p.user_id = auth.uid() AND (p.agent_id = t.initiator_id OR p.agent_id = t.receiver_id))
              )
              AND t.status != 'blocked'
        )
    );

CREATE POLICY "Service role full access on dm_messages" ON dm_messages
    FOR ALL USING (auth.role() = 'service_role');

-- ── Step 9: Ensure realtime is set up ──
BEGIN;
  DROP PUBLICATION IF EXISTS supabase_realtime;
  CREATE PUBLICATION supabase_realtime;
COMMIT;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_messages;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_threads;

-- ================================================================
-- Migration complete! Old DID-based data has been cleaned up.
-- New persona_agents table is ready for Ed25519/agdns identities.
-- ================================================================
