-- Patch: migrate stored agent_handle='Aria' to the principal's first name.
--
-- Context: the persona/brief spec was changed so agents no longer carry the
-- default "Aria" nickname; they should introduce themselves with the user's
-- own first name. backend/agent/persona_manager.create_persona now defaults
-- to that automatically for new users, but anyone created earlier with
-- agent_handle = 'Aria' is still stuck. This patch rewrites those rows in
-- one pass.
--
-- Idempotent: re-running the UPDATE after the values are already migrated
-- is a no-op (the WHERE clause matches zero rows the second time).
--
-- Active agents pick up the new handle on their next chat turn — the
-- orchestrator reads it from persona_agents on every request. No app
-- restart needed.

UPDATE persona_agents
SET agent_handle = NULLIF(SPLIT_PART(TRIM(COALESCE(name, '')), ' ', 1), '')
WHERE agent_handle = 'Aria';

-- Verify (expect zero):
-- SELECT COUNT(*) FROM persona_agents WHERE agent_handle = 'Aria';

-- Force PostgREST to reload its schema cache (harmless if there's no
-- schema change; this just keeps consistency with our other patches).
NOTIFY pgrst, 'reload schema';
