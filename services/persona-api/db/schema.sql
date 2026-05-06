-- ================================================================
-- Zynd AI — Complete Database Schema (v3 — A2A v0.3 transport)
--
-- One-shot schema for a fresh Supabase project. Run this in the
-- Supabase SQL Editor and you're done — no patches needed.
--
-- Encompasses every prior migration:
--   • migrate_v2.sql                    (Ed25519 / agdns → zns rename)
--   • patch_add_profile.sql             (persona_agents.profile JSONB)
--   • patch_add_agent_handle.sql        (persona_agents.agent_handle)
--   • patch_dm_thread_modes.sql         (legacy single-mode, superseded)
--   • patch_dm_thread_modes_per_side.sql (initiator_mode/receiver_mode)
--   • patch_dm_message_channels.sql     (dm_messages.channel)
--   • patch_agent_tasks_and_permissions.sql (agent_tasks + dm_threads.permissions)
--   • patch_telegram_persistence.sql    (telegram_links/chat_history)
--   • supabase/migrations/001 (linkedin_profiles)
--   • supabase/migrations/002 (dm_threads.lifecycle)
--   • supabase/migrations/003 (pending_approvals)
--   • patch_a2a_v3.sql                  (a2a_tasks + connection FSM expansion)
--
-- Tables (FK dependency order — children before parents):
--   1. api_tokens
--   2. chat_messages
--   3. persona_agents
--   4. dm_threads
--   5. dm_messages
--   6. agent_tasks
--   7. a2a_tasks
--   8. pending_approvals
--   9. telegram_links / telegram_chat_history
--  10. linkedin_profiles
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

CREATE POLICY "Service role full access on api_tokens"
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

CREATE POLICY "Service role full access on chat_messages"
    ON chat_messages FOR ALL
    USING (auth.role() = 'service_role');


-- ================================================================
-- 3. PERSONA AGENTS — maps Supabase users to Zynd Network agent IDs
--
-- One row per active persona. Identity is HD-derived from the
-- developer keypair at `derivation_index`; the agent_id is what the
-- registry assigns. The webhook_url stored here is the v3 A2A
-- JSON-RPC endpoint (`<base>/api/persona/{user_id}/a2a/v1`); peers
-- POST signed JSON-RPC envelopes to it.
-- ================================================================
CREATE TABLE IF NOT EXISTS persona_agents (
    user_id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    agent_id          TEXT NOT NULL UNIQUE,        -- zns:... format (registry-assigned)
    derivation_index  INTEGER NOT NULL UNIQUE,     -- HD index from developer key
    public_key        TEXT NOT NULL,               -- ed25519:<b64>
    name              TEXT NOT NULL,               -- principal's display name (advertised on the network)
    agent_handle      TEXT,                        -- optional AI agent nickname (internal-only, never advertised)
    description       TEXT NOT NULL DEFAULT '',
    capabilities      JSONB DEFAULT '[]'::jsonb,
    profile           JSONB DEFAULT '{}'::jsonb,   -- {title, organization, location, interests, twitter, linkedin, ...}
    webhook_url       TEXT,                        -- v3 A2A endpoint URL
    active            BOOLEAN DEFAULT true,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE persona_agents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own persona" ON persona_agents
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own persona" ON persona_agents
    FOR UPDATE USING (auth.uid() = user_id);

-- Public read for agent discovery (other users need to look up agent_ids).
CREATE POLICY "Public read persona agents" ON persona_agents
    FOR SELECT USING (true);

CREATE POLICY "Service role full access on persona_agents" ON persona_agents
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 4. DM THREADS — directed connections between two agents
--
-- Two distinct status fields:
--   `status`     — ConnectionFSM (v3 §3.1):
--                  pending → accepted | declined | blocked → revoked
--   `lifecycle`  — agent-conversation phase:
--                  pending → active → needs_human → human_handling
--   `{initiator,receiver}_mode` — per-side AI/human mode toggle
--   `permissions` — per-thread capability gates the orchestrator
--                   honors in external mode (frozen on each task)
--
-- Participant ids are TEXT (not UUID FKs) to support both Supabase
-- user UUIDs and `zns:`-prefixed agent ids.
-- ================================================================
CREATE TABLE IF NOT EXISTS dm_threads (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    initiator_id  TEXT NOT NULL,
    receiver_id   TEXT NOT NULL,
    initiator_name TEXT DEFAULT '',
    receiver_name  TEXT DEFAULT '',
    -- ConnectionFSM (§3.1). Receiver can decline / block; either side
    -- can revoke an accepted connection. Phase 4 added 'declined' and
    -- 'revoked' to support the full state set the v3 spec requires.
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked')),
    -- Agent-conversation phase. Independent of `status`. Read by the
    -- frontend to render the "Agents talking" / "Needs you" pill.
    lifecycle     TEXT NOT NULL DEFAULT 'pending',
    -- Per-side mode: each participant can independently be 'human'
    -- (taken over manually) or 'agent' (AI handles inbound traffic on
    -- the agent channel). The receiving handler checks OUR side's mode
    -- before dispatching the orchestrator.
    initiator_mode TEXT NOT NULL DEFAULT 'agent' CHECK (initiator_mode IN ('human', 'agent')),
    receiver_mode  TEXT NOT NULL DEFAULT 'agent' CHECK (receiver_mode IN ('human', 'agent')),
    -- Per-connection capability toggles. Defaults are conservative —
    -- only meeting requests are on out of the box; the user opts in
    -- to the rest from the connection drawer. Captured per-task at
    -- dispatch time (frozen on a2a_tasks.permission_snapshot).
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

CREATE INDEX IF NOT EXISTS dm_threads_lifecycle_idx ON dm_threads (lifecycle);

ALTER TABLE dm_threads ENABLE ROW LEVEL SECURITY;

-- Users can see threads where they participate (via UUID or agent_id).
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

-- Either participant can update (accept/decline/block/revoke, mode/perm changes).
CREATE POLICY "Participants can update threads" ON dm_threads
    FOR UPDATE USING (
        auth.uid()::text = initiator_id
        OR auth.uid()::text = receiver_id
        OR EXISTS (SELECT 1 FROM persona_agents WHERE user_id = auth.uid() AND (agent_id = initiator_id OR agent_id = receiver_id))
    );

CREATE POLICY "Service role full access on dm_threads" ON dm_threads
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 5. DM MESSAGES — individual messages within threads
--
-- Two channels live on the same thread:
--   'human' (default) — typed by humans in MessagesPanel
--   'agent'           — produced by orchestrators on either side, or
--                       the human-typing-on-agent-channel endpoint
-- The frontend tabs route by channel; subscribers filter likewise.
-- ================================================================
CREATE TABLE IF NOT EXISTS dm_messages (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    thread_id     UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    sender_id     TEXT NOT NULL,           -- user UUID or zns:... agent_id
    sender_type   TEXT NOT NULL DEFAULT 'human'
                  CHECK (sender_type IN ('human', 'agent', 'system')),
    channel       TEXT NOT NULL DEFAULT 'human'
                  CHECK (channel IN ('human', 'agent')),
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
              AND t.status NOT IN ('blocked', 'revoked')
        )
    );

CREATE POLICY "Users can send messages in accepted threads" ON dm_messages
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
              AND t.status NOT IN ('blocked', 'declined', 'revoked')
        )
    );

CREATE POLICY "Service role full access on dm_messages" ON dm_messages
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 6. AGENT TASKS — structured cross-agent tickets (meetings, etc.)
--
-- Both participants share the same row. Status flows:
--   proposed → countered → accepted → scheduled
--                       ↘            ↘
--                        declined     book_failed
--                                     cancelled
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
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {title, start_time, end_time, location, description}
    history             JSONB NOT NULL DEFAULT '[]'::jsonb,   -- audit trail of edits
    calendar_event_ids  JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {initiator: '...', recipient: '...'}
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_tasks_thread_idx     ON agent_tasks (thread_id);
CREATE INDEX IF NOT EXISTS agent_tasks_initiator_idx  ON agent_tasks (initiator_user_id);
CREATE INDEX IF NOT EXISTS agent_tasks_recipient_idx  ON agent_tasks (recipient_user_id);
CREATE INDEX IF NOT EXISTS agent_tasks_status_idx     ON agent_tasks (status);

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
-- 7. A2A TASKS — A2A v0.3 task FSM persistence
--
-- One row per cross-agent JSON-RPC task. Mirrors the in-memory task
-- store so cross-process restarts can reconcile in-flight work to a
-- clean failure rather than dropping tasks on the floor.
--
-- contextId in A2A v0.3 IS our dm_threads.id (invariant C-1):
-- contextId is what makes a multi-task negotiation feel like one
-- conversation. Each request inside the connection gets its own
-- taskId; many tasks share the same contextId.
--
-- Permission snapshot is frozen at dispatch (T-3) — a permission
-- edit mid-task can't retroactively change handler behavior.
-- ================================================================
CREATE TABLE IF NOT EXISTS a2a_tasks (
    task_id              UUID PRIMARY KEY,
    context_id           UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    -- Matches zyndai_agent.a2a.types.TaskState (A2A v0.3 spec).
    state                TEXT NOT NULL DEFAULT 'submitted'
                         CHECK (state IN (
                             'submitted', 'working',
                             'input-required', 'auth-required',
                             'completed', 'canceled', 'failed', 'rejected'
                         )),
    -- Frozen-at-dispatch copy of dm_threads.permissions.
    permission_snapshot  JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Wire history: list of A2A Message dicts (signed). Used by
    -- tasks/get and resubscribe replay; trimmed to historyLength on read.
    history              JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Wire artifacts: list of A2A Artifact dicts.
    artifacts            JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Push notification config (caller-supplied).
    push_url             TEXT,
    push_token           TEXT,
    -- Most recent A2A Message.messageId observed, for the
    -- (contextId, messageId) dedup window (M-2).
    last_message_id      TEXT,
    -- IDLE_TTL_INTERRUPTED default; the GC sweeper transitions
    -- interrupted tasks past this deadline to 'failed'.
    idle_ttl_ms          BIGINT NOT NULL DEFAULT 3600000,
    idle_until           TIMESTAMPTZ,
    terminal_at          TIMESTAMPTZ,
    -- Free-form reason string for failed/canceled/rejected.
    failure_reason       TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS a2a_tasks_context_idx
    ON a2a_tasks (context_id, updated_at DESC);
-- Partial index drives the idle-TTL sweeper.
CREATE INDEX IF NOT EXISTS a2a_tasks_state_idle_idx
    ON a2a_tasks (state, idle_until)
    WHERE state IN ('input-required', 'auth-required');

ALTER TABLE a2a_tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Participants can read a2a_tasks" ON a2a_tasks
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM dm_threads t
            WHERE t.id = a2a_tasks.context_id
              AND (
                  t.initiator_id = auth.uid()::text
                  OR t.receiver_id = auth.uid()::text
                  OR EXISTS (
                      SELECT 1 FROM persona_agents p
                      WHERE p.user_id = auth.uid()
                        AND (p.agent_id = t.initiator_id OR p.agent_id = t.receiver_id)
                  )
              )
        )
    );

CREATE POLICY "Service role full access on a2a_tasks" ON a2a_tasks
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 8. PENDING APPROVALS — external-mode tool-call gate
--
-- When a foreign agent's request would invoke a commitment-class
-- tool (propose_meeting, send_email, post on socials, etc.), the
-- orchestrator stages it here instead of firing. The user resolves
-- each row from the UI; on approve we re-run the tool with the
-- saved args, on decline we drop a polite refusal back to the
-- foreign side.
-- ================================================================
CREATE TABLE IF NOT EXISTS pending_approvals (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id   UUID REFERENCES dm_threads(id) ON DELETE CASCADE,
    tool_name   TEXT NOT NULL,
    tool_args   JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary     TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'declined', 'expired')),
    result      JSONB,
    created_at  TIMESTAMPTZ DEFAULT now(),
    decided_at  TIMESTAMPTZ,
    -- Auto-expire so abandoned approvals don't pile up forever. The
    -- list endpoint also lazily flips overdue rows to 'expired'.
    expires_at  TIMESTAMPTZ DEFAULT (now() + interval '24 hours')
);

CREATE INDEX IF NOT EXISTS pending_approvals_user_status_idx
    ON pending_approvals (user_id, status);
CREATE INDEX IF NOT EXISTS pending_approvals_thread_idx
    ON pending_approvals (thread_id);

ALTER TABLE pending_approvals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own approvals" ON pending_approvals
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users update own approvals" ON pending_approvals
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on pending_approvals" ON pending_approvals
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 9. TELEGRAM — persistent link map + per-chat conversation history
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
-- 10. LINKEDIN PROFILES — cached Apify scrape per user
-- ================================================================
CREATE TABLE IF NOT EXISTS linkedin_profiles (
    user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    profile_url  TEXT,
    scraped_at   TIMESTAMPTZ,
    raw_profile  JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_posts    JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS linkedin_profiles_scraped_at_idx
    ON linkedin_profiles (scraped_at DESC);

ALTER TABLE linkedin_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own linkedin profile" ON linkedin_profiles
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users delete own linkedin profile" ON linkedin_profiles
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access on linkedin_profiles" ON linkedin_profiles
    FOR ALL USING (auth.role() = 'service_role');


-- ================================================================
-- 11. REALTIME PUBLICATION
--
-- Frontend subscribes to these tables for live updates:
--   • dm_threads        — connection state, lifecycle, mode toggles
--   • dm_messages       — chat + agent-channel messages
--   • agent_tasks       — meeting tickets
--   • a2a_tasks         — Task FSM transitions (Task badges in the UI)
--   • pending_approvals — staged approvals show up live in chat
-- ================================================================
BEGIN;
  DROP PUBLICATION IF EXISTS supabase_realtime;
  CREATE PUBLICATION supabase_realtime;
COMMIT;

ALTER PUBLICATION supabase_realtime ADD TABLE dm_threads;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_messages;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_tasks;
ALTER PUBLICATION supabase_realtime ADD TABLE a2a_tasks;
ALTER PUBLICATION supabase_realtime ADD TABLE pending_approvals;
