-- Migration: manual toggle for brief-driven todo auto-extraction
--
-- Adds persona_agents.auto_extract_todos (default true, so existing
-- behavior is unchanged for everyone until they flip it off). The
-- Todos tab surfaces this as a switch; when off, brief_watcher.py
-- skips the user's periodic LLM extraction sweep, but the manual
-- "Refresh from brief" button in the UI still works on demand.

ALTER TABLE persona_agents
  ADD COLUMN IF NOT EXISTS auto_extract_todos BOOLEAN NOT NULL DEFAULT true;
