-- Pending group invitations: owner/admin invites a specific user by
-- user_id; the invitee accepts/declines from their inbox before they
-- become a `persona_group_members` row.

CREATE TABLE IF NOT EXISTS persona_group_invitations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id         UUID NOT NULL REFERENCES persona_groups(id) ON DELETE CASCADE,
    invitee_user_id  UUID NOT NULL REFERENCES auth.users(id)     ON DELETE CASCADE,
    inviter_user_id  UUID          REFERENCES auth.users(id)     ON DELETE SET NULL,
    invitee_role     TEXT NOT NULL DEFAULT 'member'
                     CHECK (invitee_role IN ('admin', 'member')),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')),
    message          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at       TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '7 days'
);

-- At most one open invitation per (group, invitee). Resolved rows stay
-- for audit; the partial index frees the slot for re-inviting.
CREATE UNIQUE INDEX IF NOT EXISTS persona_group_invitations_open_uniq
    ON persona_group_invitations (group_id, invitee_user_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS persona_group_invitations_invitee_status_idx
    ON persona_group_invitations (invitee_user_id, status);

CREATE INDEX IF NOT EXISTS persona_group_invitations_group_status_idx
    ON persona_group_invitations (group_id, status);

DO $$
BEGIN
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE persona_group_invitations;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;
