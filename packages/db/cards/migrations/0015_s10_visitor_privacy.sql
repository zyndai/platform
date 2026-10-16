-- owner: cards
-- Expand-only named-visitor storage; existing analytics remains independent.
-- Rollback: disable the visitor UI/endpoints; retain consent and history tables.
CREATE TABLE "cards"."profile_visits" (
	"id" uuid PRIMARY KEY NOT NULL,
	"card_id" text NOT NULL,
	"visitor_id" uuid NOT NULL,
	"consent_version" uuid NOT NULL,
	"visited_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."profile_visits" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."visitor_preferences" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"anonymous_mode" boolean DEFAULT true NOT NULL,
	"display_name" text,
	"consent_version" uuid DEFAULT gen_random_uuid() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."visitor_preferences" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."profile_visits" ADD CONSTRAINT "profile_visits_card_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."profile_visits" ADD CONSTRAINT "profile_visits_visitor_fkey" FOREIGN KEY ("visitor_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."visitor_preferences" ADD CONSTRAINT "visitor_preferences_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "profile_visits_card_time_idx" ON "cards"."profile_visits" USING btree ("card_id","visited_at");--> statement-breakpoint
CREATE INDEX "profile_visits_visitor_idx" ON "cards"."profile_visits" USING btree ("visitor_id");--> statement-breakpoint
CREATE POLICY "service role full access on profile_visits" ON "cards"."profile_visits" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on visitor_preferences" ON "cards"."visitor_preferences" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);