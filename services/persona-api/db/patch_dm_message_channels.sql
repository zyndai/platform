-- ================================================================
-- Patch: dm_messages.channel — separate human chat from agent chatter
--
-- The same connection now carries TWO logical channels:
--
--   'human' (default) — messages typed by humans in MessagesPanel.
--                       Visible in the Conversation tab. The other side's
--                       agent does NOT auto-reply to these.
--
--   'agent'           — messages produced by orchestrators on either side
--                       (negotiations, scheduling probes, automation
--                       chatter). Visible in the Agent Activity tab as a
--                       transparency log. The orchestrator routes inbound
--                       agent-channel messages back through itself if the
--                       thread mode permits.
--
-- The channel is implicit in the transport: anything received via the
-- cross-agent webhook is by definition the agent channel; anything
-- inserted by the Supabase client (the human typing) is the human
-- channel. No payload-level field needed for v1 (single backend).
-- ================================================================

ALTER TABLE dm_messages
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'human'
    CHECK (channel IN ('human', 'agent'));
