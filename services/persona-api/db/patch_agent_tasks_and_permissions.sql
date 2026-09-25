-- ================================================================
-- Patch: Chunk 1 — agent_tasks ticket store + per-connection permissions
--
-- Adds the building blocks for the structured cross-agent task workflow
-- (meetings, introductions, etc.) and a per-thread permission set so
-- the user can control what an external agent is allowed to ask for on
-- their behalf.
--
--   1. agent_tasks: tickets with a state machine. Both participants
--      see the same row (we're same-platform for v1) and either side
--      can update it. Status flows:
--          proposed → countered → accepted → scheduled
--                              ↘            ↘
--                               declined     book_failed
--                                            cancelled
--
--   2. dm_threads.permissions: JSONB column with four boolean toggles
--      (defaults are conservative). The orchestrator's external mode
--      reads these and refuses anything not granted.
-- ================================================================


-- ── 1. agent_tasks ──────────────────────────────────────────────────

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
    initiator_agent_id  TEXT NOT NULL,         -- agdns:/zns: id
    recipient_agent_id  TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {title, start_time, end_time, location, description}
    history             JSONB NOT NULL DEFAULT '[]'::jsonb,   -- audit trail of edits
    calendar_event_ids  JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {initiator: '...', recipient: '...'} after booking
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_tasks_thread_idx ON agent_tasks (thread_id);
CREATE INDEX IF NOT EXISTS agent_tasks_initiator_idx ON agent_tasks (initiator_user_id);
CREATE INDEX IF NOT EXISTS agent_tasks_recipient_idx ON agent_tasks (recipient_user_id);
CREATE INDEX IF NOT EXISTS agent_tasks_status_idx ON agent_tasks (status);

ALTER TABLE agent_tasks ENABLE ROW LEVEL SECURITY;

-- Either participant can read their own tickets
CREATE POLICY "Participants can read agent_tasks" ON agent_tasks
    FOR SELECT USING (
        auth.uid() = initiator_user_id OR auth.uid() = recipient_user_id
    );

-- Either participant can update their tickets (status changes, edits, etc.)
CREATE POLICY "Participants can update agent_tasks" ON agent_tasks
    FOR UPDATE USING (
        auth.uid() = initiator_user_id OR auth.uid() = recipient_user_id
    );

-- Service role full access (orchestrator + booking worker)
CREATE POLICY "Service role full access on agent_tasks" ON agent_tasks
    FOR ALL USING (auth.role() = 'service_role');


-- ── 2. dm_threads.permissions ────────────────────────────────────────
--
-- Per-thread capability toggles. The defaults are conservative — only
-- meeting requests are on by default; everything else is opt-in.
-- The user can flip these from the connection settings drawer.

ALTER TABLE dm_threads
    ADD COLUMN IF NOT EXISTS permissions JSONB NOT NULL DEFAULT
        jsonb_build_object(
            'can_request_meetings',  true,
            'can_query_availability', false,
            'can_view_full_profile',  false,
            'can_post_on_my_behalf',  false
        );


-- ── 3. Realtime ──────────────────────────────────────────────────────

ALTER PUBLICATION supabase_realtime ADD TABLE agent_tasks;
