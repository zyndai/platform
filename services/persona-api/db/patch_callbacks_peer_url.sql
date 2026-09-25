-- ================================================================
-- Patch: store the peer's A2A endpoint URL on outbound_callbacks.
--
-- When a peer pushes back a status-only callback, the inbound handler
-- must call `tasks/get` against the peer to pull the real result. The
-- callback row knew the peer's agent_id but not the URL we dispatched
-- to, forcing a live registry re-resolution. We already hold the exact
-- URL at dispatch time, so persist it and skip the round-trip.
--
-- Additive + idempotent — safe to apply on a live table. Legacy rows
-- keep peer_a2a_url NULL; the handler falls back to registry resolution
-- for those.
-- ================================================================

ALTER TABLE outbound_callbacks ADD COLUMN IF NOT EXISTS peer_a2a_url TEXT;
