-- ================================================================
-- Patch: outbound A2A callbacks (push-mode response correlation)
--
-- Adds the symmetric outbound side of a2a_tasks — when this persona
-- sends a push-mode message to another agent, we keep a row pending
-- until the peer's eventual push notification arrives. The peer's
-- delayed reply (which can take seconds to days for human-mode
-- threads) lands as a callback_results row, fans out to the open
-- frontend chat via Supabase realtime, and updates the originating
-- conversation/tool-call site.
--
-- Two tables:
--
--   1. outbound_callbacks — one row per push-mode send awaiting reply.
--      Holds the bearer token the peer must echo when pushing back
--      (mandatory: without bearer match, any signed peer could write
--      into anyone's callback log). Holds origin metadata so the
--      eventual reply routes to the right surface (chat thread,
--      LLM tool result, agent-send hand-off).
--
--   2. callback_results — one row per inbound push event matched to
--      an outbound_callback. The frontend subscribes to this table
--      filtered by user_id; arrivals push live into the open chat.
-- ================================================================


-- ── 1. outbound_callbacks ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS outbound_callbacks (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- contextId on the wire = our dm_threads.id. Soft-FK because the
    -- thread row may legitimately be missing during early bootstrap;
    -- we don't want to lose callbacks to an FK violation.
    thread_id         UUID NOT NULL,
    -- The peer entity's id (zns:… or agdns:… per-network convention).
    peer_agent_id     TEXT NOT NULL,
    -- The Task.id the peer assigned to our message — filled in once
    -- the receiver responds to message/send. Used as a secondary
    -- correlation key alongside the bearer token (defence in depth).
    peer_task_id      TEXT,
    -- Our outbound A2A messageId — the peer echoes this in their
    -- task.history so we can match by it as well.
    our_message_id    TEXT NOT NULL,
    -- What in our world triggered the send. Drives where the eventual
    -- reply lands in the UI:
    --   'chat'        → ChatInterface, inject into conversation
    --   'agent_send'  → DM thread page only
    --   'mcp_tool'    → LLM tool-result loop (orchestrator picks back up)
    --   'meeting'     → meeting flow notification
    origin_kind       TEXT NOT NULL,
    origin_ref        JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Bearer token we issue to the peer; format `cb_<base64url(16)>`.
    -- Phase 4's push receiver MUST match this against
    -- Authorization: Bearer <token> before writing a callback_result.
    push_token        TEXT NOT NULL UNIQUE,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'received', 'expired', 'failed')),
    -- Tasks with no inbound push by this point are flipped to 'expired'
    -- by the GC sweeper. Default 24h — long enough for human-mode
    -- replies but short enough to bound the row count.
    expires_at        TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours'),
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outbound_callbacks_user_idx
    ON outbound_callbacks (user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS outbound_callbacks_peer_task_idx
    ON outbound_callbacks (peer_agent_id, peer_task_id)
    WHERE peer_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS outbound_callbacks_expires_idx
    ON outbound_callbacks (expires_at)
    WHERE status = 'pending';

ALTER TABLE outbound_callbacks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owner reads outbound_callbacks" ON outbound_callbacks
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Service role full access on outbound_callbacks" ON outbound_callbacks
    FOR ALL USING (auth.role() = 'service_role');


-- ── 2. callback_results ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS callback_results (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    callback_id       UUID NOT NULL REFERENCES outbound_callbacks(id) ON DELETE CASCADE,
    -- Denormalized so RLS + realtime publication filter is cheap.
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id         UUID NOT NULL,
    peer_agent_id     TEXT NOT NULL,
    -- A2A v0.3 TaskState the peer reported. Matches outbound_callbacks
    -- terminal-state semantics — 'completed' / 'failed' / 'rejected'
    -- close the callback; 'input-required' / 'auth-required' keep it
    -- open and just surface a partial update.
    task_state        TEXT NOT NULL,
    -- Plain-text reply extracted from the inbound TaskStatusUpdateEvent
    -- (or empty if the peer only sent structured data).
    reply_text        TEXT,
    -- Full event JSON for cases where the UI wants to render rich
    -- structured replies, attachments, or tool-result data.
    raw_event         JSONB NOT NULL,
    -- Flips to TRUE once the frontend confirms it rendered the result.
    -- Drives the "unread" badge and the GC retention sweeper (rows
    -- delivered_to_ui = TRUE older than 30d are eligible for purge).
    delivered_to_ui   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS callback_results_user_idx
    ON callback_results (user_id, delivered_to_ui, created_at DESC);
CREATE INDEX IF NOT EXISTS callback_results_thread_idx
    ON callback_results (thread_id, created_at DESC);

ALTER TABLE callback_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owner reads callback_results" ON callback_results
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Owner marks delivered" ON callback_results
    FOR UPDATE USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "Service role full access on callback_results" ON callback_results
    FOR ALL USING (auth.role() = 'service_role');


-- ── 3. Realtime publication ──────────────────────────────────────────
-- Frontend subscribes to callback_results filtered by user_id so an
-- inbound push surfaces in the open ChatInterface without a refresh.
ALTER PUBLICATION supabase_realtime ADD TABLE callback_results;
