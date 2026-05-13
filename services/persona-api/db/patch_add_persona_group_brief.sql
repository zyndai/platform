-- Patch: persona_groups brief Google Doc fields
--
-- Phase 3a — each group gets a shared brief that lives in the owner's
-- Google Drive. Stored on the group row so it's discoverable from the
-- chat view without an extra table read. The actual content is fetched
-- live (or read through the existing brief_watcher / docs MCP tools),
-- so the columns only hold the doc id + a UI-friendly link.
--
-- Permission model: any member can READ via the API (with `can_see_brief`
-- still gating what's exposed cross-persona at dispatch time); only the
-- owner or admin can WRITE. The doc itself remains in the owner's Drive,
-- so revoking their Google connection or archiving the group cuts off
-- access cleanly without us having to migrate the doc anywhere.

ALTER TABLE persona_groups
    ADD COLUMN IF NOT EXISTS brief_doc_id  TEXT,
    ADD COLUMN IF NOT EXISTS brief_doc_url TEXT;
