-- ================================================================
-- Zynd AI — Complete Database Schema (v2 — Ed25519/agdns migration)
-- Run this in the Supabase SQL Editor (http://127.0.0.1:54323)
-- ================================================================

-- ================================================================
-- 1. API TOKENS — OAuth access/refresh tokens per provider per user
-- ================================================================
CREATE TABLE IF NOT EXISTS api_tokens (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,          -- 'linkedin', 'twitter', 'google', 'notion'
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    expires_at    TIMESTAMPTZ,
    scopes        TEXT,                   -- space-separated scopes
    raw_data      JSONB DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, provider)
);

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

CREATE POLICY "Service role full access"
    ON api_tokens FOR ALL
    USING (auth.role() = 'service_role');


-- ================================================================
-- 2. CHAT MESSAGES — conversation persistence (future use)
-- ================================================================
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


-- ================================================================
-- 3. PERSONA AGENTS — maps Supabase users to Zynd Network agent IDs
--    Replaces the old persona_dids table (DID → agdns migration)
-- ================================================================
CREATE TABLE IF NOT EXISTS persona_agents (
    user_id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    agent_id          TEXT NOT NULL UNIQUE,        -- agdns:... format
    derivation_index  INTEGER NOT NULL UNIQUE,     -- HD key derivation index from developer key
    public_key        TEXT NOT NULL,               -- ed25519:... format
    name              TEXT NOT NULL,             -- principal's display name (registered with the network)
    agent_handle      TEXT,                       -- optional AI agent's own name (internal only, never advertised)
    description       TEXT NOT NULL DEFAULT '',
    capabilities      JSONB DEFAULT '[]'::jsonb,
    profile           JSONB DEFAULT '{}'::jsonb,  -- social links, title, org, location, interests
    webhook_url       TEXT,
    active            BOOLEAN DEFAULT true,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE persona_agents ENABLE ROW LEVEL SECURITY;

-- Users can read their own persona
CREATE POLICY "Users can read own persona" ON persona_agents
    FOR SELECT USING (auth.uid() = user_id);

-- Users can update their own persona
CREATE POLICY "Users can update own persona" ON persona_agents
    FOR UPDATE USING (auth.uid() = user_id);

-- Public read for agent discovery (other users need to see agent_ids)
CREATE POLICY "Public read persona agents" ON persona_agents
    FOR SELECT USING (true);

-- Service role has full access
CREATE POLICY "Service role full access on persona_agents" ON persona_agents
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 4. DM THREADS — direct messaging between agents
--    Uses TEXT for IDs to support both UUID and agdns: format
-- ================================================================
CREATE TABLE IF NOT EXISTS dm_threads (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    initiator_id  TEXT NOT NULL,           -- user UUID or agdns:... agent_id
    receiver_id   TEXT NOT NULL,           -- user UUID or agdns:... agent_id
    initiator_name TEXT DEFAULT '',
    receiver_name  TEXT DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'accepted', 'blocked'
    -- Per-side mode: each participant can independently be in 'human'
    -- (taken over, no AI auto-reply) or 'agent' (AI handles incoming
    -- messages on the agent channel). The receiving webhook handler
    -- checks OUR mode (the side whose user_id owns the webhook) to
    -- decide whether to invoke the orchestrator.
    initiator_mode TEXT NOT NULL DEFAULT 'agent' CHECK (initiator_mode IN ('human', 'agent')),
    receiver_mode  TEXT NOT NULL DEFAULT 'agent' CHECK (receiver_mode IN ('human', 'agent')),
    -- Per-connection capability toggles enforced by the orchestrator's
    -- external mode. Defaults are conservative; the user opts the other
    -- side in from the connection settings drawer.
    permissions   JSONB NOT NULL DEFAULT jsonb_build_object(
                      'can_request_meetings',  true,
                      'can_query_availability', false,
                      'can_view_full_profile',  false,
                      'can_post_on_my_behalf',  false
                  ),
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(initiator_id, receiver_id)
);

ALTER TABLE dm_threads ENABLE ROW LEVEL SECURITY;

-- Users can see threads where they participate (via UUID or agent_id)
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

-- Service role full access for backend webhook processing
CREATE POLICY "Service role full access on dm_threads" ON dm_threads
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 5. DM MESSAGES — individual messages within threads
-- ================================================================
CREATE TABLE IF NOT EXISTS dm_messages (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    thread_id     UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    sender_id     TEXT NOT NULL,           -- user UUID or agdns:... agent_id
    -- Who actually produced this message: a human typing in MessagesPanel,
    -- the orchestrator (ours or theirs), or a system status notice.
    sender_type   TEXT NOT NULL DEFAULT 'human' CHECK (sender_type IN ('human', 'agent', 'system')),
    -- Which channel of the connection this message belongs to:
    --   'human' = typed by a human in MessagesPanel (Conversation tab)
    --   'agent' = produced by an orchestrator (Agent Activity tab)
    -- The channel is implicit in the transport: webhook ingress → agent,
    -- direct Supabase insert from the UI → human.
    channel       TEXT NOT NULL DEFAULT 'human' CHECK (channel IN ('human', 'agent')),
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE dm_messages ENABLE ROW LEVEL SECURITY;

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

-- Service role full access for backend webhook processing
CREATE POLICY "Service role full access on dm_messages" ON dm_messages
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 6. AGENT TASKS — structured cross-agent tickets (meetings, etc.)
--    Both participants share the same row (same-platform v1).
-- ================================================================
CREATE TABLE IF NOT EXISTS agent_tasks (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    thread_id           UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    type                TEXT NOT NULL DEFAULT 'meeting'
                        CHECK (type IN ('meeting')),
    status              TEXT NOT NULL DEFAULT 'proposed'
                        CHECK (status IN (
                            'proposed', 'countered', 'accepted',
                            'scheduled', 'declined', 'cancelled', 'book_failed'
                        )),
    initiator_user_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    recipient_user_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    initiator_agent_id  TEXT NOT NULL,
    recipient_agent_id  TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    history             JSONB NOT NULL DEFAULT '[]'::jsonb,
    calendar_event_ids  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_tasks_thread_idx ON agent_tasks (thread_id);
CREATE INDEX IF NOT EXISTS agent_tasks_initiator_idx ON agent_tasks (initiator_user_id);
CREATE INDEX IF NOT EXISTS agent_tasks_recipient_idx ON agent_tasks (recipient_user_id);
CREATE INDEX IF NOT EXISTS agent_tasks_status_idx ON agent_tasks (status);

ALTER TABLE agent_tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Participants can read agent_tasks" ON agent_tasks
    FOR SELECT USING (
        auth.uid() = initiator_user_id OR auth.uid() = recipient_user_id
    );

CREATE POLICY "Participants can update agent_tasks" ON agent_tasks
    FOR UPDATE USING (
        auth.uid() = initiator_user_id OR auth.uid() = recipient_user_id
    );

CREATE POLICY "Service role full access on agent_tasks" ON agent_tasks
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 7. TELEGRAM — persistent link map + per-chat conversation history
--    Replaces the old telegram_users.json file and the in-memory
--    _conversations dict for Telegram traffic.
-- ================================================================
CREATE TABLE IF NOT EXISTS telegram_links (
    user_id    UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    chat_id    TEXT NOT NULL UNIQUE,
    linked_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS telegram_links_chat_idx ON telegram_links (chat_id);
ALTER TABLE telegram_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own telegram link" ON telegram_links
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users delete own telegram link" ON telegram_links
    FOR DELETE USING (auth.uid() = user_id);
CREATE POLICY "Service role full access on telegram_links" ON telegram_links
    FOR ALL USING (auth.role() = 'service_role');


CREATE TABLE IF NOT EXISTS telegram_chat_history (
    conversation_id  TEXT PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    messages         JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS telegram_chat_history_user_idx ON telegram_chat_history (user_id);
ALTER TABLE telegram_chat_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own telegram history" ON telegram_chat_history
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Service role full access on telegram_chat_history" ON telegram_chat_history
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 8. REALTIME SETUP
-- ================================================================
BEGIN;
  DROP PUBLICATION IF EXISTS supabase_realtime;
  CREATE PUBLICATION supabase_realtime;
COMMIT;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_messages;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_threads;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_tasks;
