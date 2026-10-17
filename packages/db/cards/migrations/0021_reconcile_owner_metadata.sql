-- owner: cards
-- Track owner metadata already present on aafo without resetting existing values.
-- IF NOT EXISTS also builds the same columns on a fresh database.
-- Rollback: revert consumers if needed; retain these additive columns and data.
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN IF NOT EXISTS "digest_opt_out" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN IF NOT EXISTS "last_looking_for_nudge_on" date;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN IF NOT EXISTS "last_owner_digest_on" date;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN IF NOT EXISTS "looking_for_expires_at" timestamp with time zone;
