-- owner: cards
-- S03 "Not me" takedown queue + S07 short share alias. Expand-only.
-- Rollback: ALTER TABLE cards.agent_profile_cards DROP CONSTRAINT agent_profile_cards_alias_key;
--           ALTER TABLE cards.agent_profile_cards DROP COLUMN alias;
--           DROP TABLE cards.takedown_requests;
CREATE TABLE "cards"."takedown_requests" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"handle" text NOT NULL,
	"requester_user_id" uuid,
	"note" text,
	"status" text DEFAULT 'pending' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."takedown_requests" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "alias" text;--> statement-breakpoint
CREATE INDEX "takedown_requests_handle_idx" ON "cards"."takedown_requests" USING btree ("handle");--> statement-breakpoint
CREATE INDEX "takedown_requests_status_idx" ON "cards"."takedown_requests" USING btree ("status");--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD CONSTRAINT "agent_profile_cards_alias_key" UNIQUE("alias");--> statement-breakpoint
CREATE POLICY "service role full access on takedown_requests" ON "cards"."takedown_requests" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);