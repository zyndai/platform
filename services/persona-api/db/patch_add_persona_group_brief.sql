-- Patch: persona_groups brief Google Doc fields
--
-- Phase 3a — each group gets a shared brief that lives in the owner's
-- Google Drive. Stored on the group row so it's discoverable from the
-- chat view without an extra table read. The actual content is fetched
-- live (or read through the existing brief_watcher / docs MCP tools),
-- so the columns only hold the doc id + a UI-friendly link.
--
-- Permission model: `persona_group_members.permissions.can_see_group_brief`
-- controls who can read/use the shared team brief. This is separate from
-- `can_see_member_briefs`, which controls whether a member's @mentions may
-- receive private details from another member's personal brief. Only owner
-- or admin can WRITE. The doc itself remains in the owner's Drive, so
-- revoking their Google connection or archiving the group cuts off access
-- cleanly without us having to migrate the doc anywhere.

ALTER TABLE persona_groups
    ADD COLUMN IF NOT EXISTS brief_doc_id  TEXT,
    ADD COLUMN IF NOT EXISTS brief_doc_url TEXT;

ALTER TABLE persona_group_members
    ALTER COLUMN permissions SET DEFAULT jsonb_build_object(
        'can_see_brief', false,
        'can_see_member_briefs', false,
        'can_see_group_brief', true,
        'can_query_calendar', true,
        'can_post', true,
        'can_invite', false,
        'can_speak_for_group', false
    );

UPDATE persona_group_members
SET permissions =
    permissions
    || jsonb_build_object(
        'can_see_member_briefs', COALESCE((permissions->>'can_see_member_briefs')::boolean, (permissions->>'can_see_brief')::boolean, false),
        'can_see_group_brief', COALESCE((permissions->>'can_see_group_brief')::boolean, true)
    )
WHERE NOT (permissions ? 'can_see_member_briefs')
   OR NOT (permissions ? 'can_see_group_brief');
