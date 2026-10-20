-- owner: cards
-- A2 "invite to claim": a Card owner invites someone who has no claimed Card yet. The target
-- is a pre-filled UNCLAIMED card; when its owner claims it, each pending invite is delivered
-- as an ordinary connection request. Expand-only: one new table, nothing existing changes.
-- Writes are service-role only (cards-api), like the rest of the Cards network.
-- Do not apply to prod without a human (AGENTS.md §6).
-- Rollback (after reverting cards-api, which stops writing it):
--   DROP TABLE cards.connection_invites;
CREATE TABLE "cards"."connection_invites" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"inviter_user_id" uuid NOT NULL,
	"inviter_card_id" text NOT NULL,
	"target_card_id" text NOT NULL,
	"message" text,
	"status" text DEFAULT 'pending' NOT NULL,
	"connection_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"delivered_at" timestamp with time zone,
	"expires_at" timestamp with time zone DEFAULT (now() + '60 days'::interval) NOT NULL,
	CONSTRAINT "cards_connection_invites_status_check" CHECK (status IN ('pending', 'delivered', 'cancelled', 'expired'))
);
--> statement-breakpoint
ALTER TABLE "cards"."connection_invites" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."connection_invites" ADD CONSTRAINT "cards_connection_invites_inviter_user_fkey" FOREIGN KEY ("inviter_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."connection_invites" ADD CONSTRAINT "cards_connection_invites_inviter_card_fkey" FOREIGN KEY ("inviter_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."connection_invites" ADD CONSTRAINT "cards_connection_invites_target_card_fkey" FOREIGN KEY ("target_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."connection_invites" ADD CONSTRAINT "cards_connection_invites_connection_fkey" FOREIGN KEY ("connection_id") REFERENCES "cards"."connections"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "cards_connection_invites_target_idx" ON "cards"."connection_invites" USING btree ("target_card_id","status");--> statement-breakpoint
CREATE INDEX "cards_connection_invites_inviter_idx" ON "cards"."connection_invites" USING btree ("inviter_user_id","created_at");--> statement-breakpoint
CREATE UNIQUE INDEX "cards_connection_invites_pending_key" ON "cards"."connection_invites" USING btree ("inviter_user_id","target_card_id") WHERE status = 'pending';--> statement-breakpoint
CREATE POLICY "service role full access on connection_invites" ON "cards"."connection_invites" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);