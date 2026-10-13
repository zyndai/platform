-- owner: cards
-- Minimal S12 activity projection; Persona remains authoritative.
-- Rollback: disable FEATURE_S12_INTROS; retain the additive table.
CREATE TABLE "cards"."intro_requests" (
	"id" uuid PRIMARY KEY NOT NULL,
	"card_id" text NOT NULL,
	"handle" text NOT NULL,
	"owner_uid" uuid NOT NULL,
	"requester_uid" uuid NOT NULL,
	"status" text NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"accepted_at" timestamp with time zone
);
--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ADD CONSTRAINT "cards_intro_card_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ADD CONSTRAINT "cards_intro_owner_fkey" FOREIGN KEY ("owner_uid") REFERENCES "auth"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."intro_requests" ADD CONSTRAINT "cards_intro_requester_fkey" FOREIGN KEY ("requester_uid") REFERENCES "auth"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "cards_intro_owner_created_idx" ON "cards"."intro_requests" USING btree ("owner_uid","created_at");--> statement-breakpoint
CREATE POLICY "service role full access on intro_requests" ON "cards"."intro_requests" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);
