-- Patch: Add brief Google Doc fields to persona_agents
--
-- The Brief is a Google Doc the agent maintains for its principal:
--   - It's the long-form context the agent uses to represent the user
--   - It's edited collaboratively (in the Zynd dashboard via embedded
--     Google Docs editor, or directly at docs.google.com)
--   - The agent reads it on every turn (with caching) instead of relying
--     on the short `persona.description` text field
--
-- All fields are nullable: a persona without a brief doc still works,
-- it just falls back to the persona.description as its briefing source.
--
-- brief_doc_revision_id is used by the doc-change watcher to detect
-- new edits and extract todos (see patch_add_brief_todos.sql).

ALTER TABLE persona_agents
  ADD COLUMN IF NOT EXISTS brief_doc_id           TEXT,
  ADD COLUMN IF NOT EXISTS brief_doc_url          TEXT,
  ADD COLUMN IF NOT EXISTS brief_doc_revision_id  TEXT;
