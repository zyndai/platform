-- ================================================================
-- Patch: Agent Calls activity surface on outbound_callbacks.
--
-- The right-rail "Agent calls" panel lists each outbound agent call and,
-- on click, shows the last raw webhook the peer pushed plus the final
-- answer. The push handler only writes a callback_results row when a
-- real result is ready, so the intermediate webhook payloads weren't
-- visible anywhere. We stash the latest push + the eventual answer on
-- the call row itself so the panel can read one table.
--
-- Additive + idempotent.
-- ================================================================

ALTER TABLE outbound_callbacks ADD COLUMN IF NOT EXISTS last_state TEXT;
ALTER TABLE outbound_callbacks ADD COLUMN IF NOT EXISTS last_event JSONB;
ALTER TABLE outbound_callbacks ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMPTZ;
ALTER TABLE outbound_callbacks ADD COLUMN IF NOT EXISTS answer_text TEXT;

-- Frontend subscribes to outbound_callbacks (owner RLS) so a dispatched
-- call shows up "pending" instantly and flips to "received" live.
DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE outbound_callbacks;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
