-- owner: cards
-- Keep new S12 records compatible with the existing explicit account/card deletion flow.
-- Replaces constraints on new S12 tables only; does not delete any data during migration.
-- Rollback: disable S12; retain these constraints to avoid blocking account deletion.
ALTER TABLE "cards"."intro_requests" DROP CONSTRAINT "cards_intro_card_fkey";
--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" DROP CONSTRAINT "cards_intro_owner_fkey";
--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" DROP CONSTRAINT "cards_intro_requester_fkey";
--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ADD CONSTRAINT "cards_intro_card_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ADD CONSTRAINT "cards_intro_owner_fkey" FOREIGN KEY ("owner_uid") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ADD CONSTRAINT "cards_intro_requester_fkey" FOREIGN KEY ("requester_uid") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;