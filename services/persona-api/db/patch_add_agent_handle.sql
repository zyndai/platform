-- ================================================================
-- Patch: add agent_handle to persona_agents
--
-- Purpose:
--   The `name` field is the human principal's display name (what shows
--   up in the registry, search, and the agent card). `agent_handle` is
--   an OPTIONAL, internal-only nickname for the AI agent itself, so it
--   can introduce itself as e.g. "Hi, I'm Alice, the AI agent
--   representing Dillu" instead of conflating itself with its
--   principal. This field is never advertised to the network.
-- ================================================================

ALTER TABLE persona_agents
    ADD COLUMN IF NOT EXISTS agent_handle TEXT;
