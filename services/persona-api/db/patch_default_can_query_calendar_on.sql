-- Flip can_query_calendar default to true.
-- Backfills only rows still at the prior unmodified default shape so an
-- owner's explicit "no" elsewhere isn't overwritten.

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
SET permissions = permissions || jsonb_build_object('can_query_calendar', true)
WHERE
    NOT (permissions ? 'can_query_calendar')
    OR (
        COALESCE((permissions->>'can_query_calendar')::boolean, false) = false
        AND COALESCE((permissions->>'can_see_member_briefs')::boolean, false) = false
        AND COALESCE((permissions->>'can_see_group_brief')::boolean, true) = true
        AND COALESCE((permissions->>'can_post')::boolean, true) = true
        AND COALESCE((permissions->>'can_invite')::boolean, false) = false
        AND COALESCE((permissions->>'can_speak_for_group')::boolean, false) = false
    );
