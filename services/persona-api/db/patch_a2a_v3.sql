-- ================================================================
-- Patch: A2A v3 — ConnectionFSM expansion + Task FSM persistence
--
-- Phase 1 of the A2A v3 redesign (see architecture v3 design doc).
-- This patch is purely additive: existing dm_threads / dm_messages /
-- agent_tasks rows continue to work unchanged. The legacy webhook
-- transport (/api/persona/webhooks/{user_id}{,/sync}) keeps running
-- until phase 6 cuts it over.
--
-- What changes:
--
--   1. dm_threads.status — adds 'declined' and 'revoked' as legal
--      states so the v3 ConnectionFSM (none → requested → accepted /
--      declined / blocked → revoked) can be represented end-to-end.
--      Existing rows (pending / accepted / blocked) are unaffected.
--
--   2. a2a_tasks — new table mirroring the in-memory TaskStore. One
--      row per cross-agent JSON-RPC task. Survives process restarts
--      so the reconciliation pass can transition orphaned 'working'
--      rows to 'failed' instead of dropping them on the floor.
--      Permission snapshot is pinned per task at dispatch (T-3) so
--      a permission edit mid-task can't retroactively change what
--      the running handler sees.
-- ================================================================


-- ── 1. dm_threads.status — extend CHECK constraint ──────────────────

ALTER TABLE dm_threads
    DROP CONSTRAINT IF EXISTS dm_threads_status_check;

ALTER TABLE dm_threads
    ADD CONSTRAINT dm_threads_status_check
    CHECK (status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked'));


-- ── 2. a2a_tasks — Task FSM persistence ─────────────────────────────

CREATE TABLE IF NOT EXISTS a2a_tasks (
    task_id              UUID PRIMARY KEY,
    -- contextId in A2A v0.3 = our dm_threads.id (invariant C-1).
    context_id           UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    -- A2A v0.3 TaskState. Matches zyndai_agent.a2a.types.TaskState
    -- byte-for-byte so wire payloads round-trip without translation.
    state                TEXT NOT NULL DEFAULT 'submitted'
                         CHECK (state IN (
                             'submitted', 'working',
                             'input-required', 'auth-required',
                             'completed', 'canceled', 'failed', 'rejected'
                         )),
    -- Frozen-at-dispatch copy of dm_threads.permissions. The handler
    -- reads from here, never from dm_threads, so a mid-task permission
    -- edit can't retroactively change behavior (invariant T-3).
    permission_snapshot  JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Wire history (list of A2A Message dicts) for tasks/get and
    -- resubscribe replay. Bounded — we trim to historyLength on read.
    history              JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Wire artifacts (list of A2A Artifact dicts).
    artifacts            JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Push notification config (caller-supplied URL + bearer token).
    -- Filled in by tasks/pushNotificationConfig/set.
    push_url             TEXT,
    push_token           TEXT,
    -- Most recent A2A Message.messageId we observed, for the
    -- (contextId, messageId) dedup window (invariant M-2).
    last_message_id      TEXT,
    -- Configurable per task; defaults to 1 hour (the design's default
    -- IDLE_TTL_INTERRUPTED). The GC sweeper transitions interrupted
    -- tasks past idle_until to 'failed'.
    idle_ttl_ms          BIGINT NOT NULL DEFAULT 3600000,
    idle_until           TIMESTAMPTZ,
    terminal_at          TIMESTAMPTZ,
    -- Free-form reason string when state ∈ {failed, canceled, rejected}.
    failure_reason       TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS a2a_tasks_context_idx
    ON a2a_tasks (context_id, updated_at DESC);
-- Used by the idle-TTL sweeper.
CREATE INDEX IF NOT EXISTS a2a_tasks_state_idle_idx
    ON a2a_tasks (state, idle_until)
    WHERE state IN ('input-required', 'auth-required');

ALTER TABLE a2a_tasks ENABLE ROW LEVEL SECURITY;

-- Either participant of the underlying dm_thread can read their tasks.
-- Same shape as the dm_messages SELECT policy: match either the user's
-- UUID or the user's persona agent_id against the thread's participants.
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

-- Service role full access (the dispatcher writes here).
CREATE POLICY "Service role full access on a2a_tasks" ON a2a_tasks
    FOR ALL USING (auth.role() = 'service_role');


-- ── 3. Realtime ──────────────────────────────────────────────────────
-- The frontend may subscribe to a2a_tasks rows in a future phase
-- (e.g. to render a Task FSM badge alongside the lifecycle pill).
-- Adding to the publication now keeps that path open without another
-- migration.
ALTER PUBLICATION supabase_realtime ADD TABLE a2a_tasks;
