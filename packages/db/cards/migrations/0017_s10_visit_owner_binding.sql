-- owner: cards
-- Expand-only named-visitor storage; existing analytics remains independent.
-- Rollback: disable the visitor UI/endpoints; retain consent and history tables.
ALTER TABLE "cards"."profile_visits" ADD COLUMN "owner_email" text NOT NULL;