-- Patch: Add profile JSONB column to persona_agents
-- Run this if you already ran migrate_v2.sql before this column was added.
ALTER TABLE persona_agents ADD COLUMN IF NOT EXISTS profile JSONB DEFAULT '{}'::jsonb;
