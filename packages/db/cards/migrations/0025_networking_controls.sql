-- owner: cards
-- Networking controls: saved searches (A3), reports of a Card and identity verifications (A6) and
-- match preferences (A8). Expand-only: four new tables, nothing existing changes. Service-role
-- only (cards-api). Do not apply to prod without a human (AGENTS.md §6).
-- Rollback (after reverting cards-api, which stops writing them):
--   DROP TABLE cards.saved_searches, cards.card_reports, cards.card_verifications, cards.match_preferences;
CREATE TABLE "cards"."match_preferences" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"kind" text NOT NULL,
	"value" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_match_preferences_key" UNIQUE("user_id","kind","value"),
	CONSTRAINT "cards_match_preferences_kind_check" CHECK (kind IN ('hide_person', 'mute_topic', 'less_like_this'))
);
--> statement-breakpoint
ALTER TABLE "cards"."match_preferences" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."card_reports" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"reporter_user_id" uuid NOT NULL,
	"target_card_id" text NOT NULL,
	"reason" text NOT NULL,
	"details" text,
	"status" text DEFAULT 'open' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_card_reports_reason_check" CHECK (reason IN ('spam', 'impersonation', 'harassment', 'inaccurate', 'other')),
	CONSTRAINT "cards_card_reports_status_check" CHECK (status IN ('open', 'reviewed', 'dismissed'))
);
--> statement-breakpoint
ALTER TABLE "cards"."card_reports" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."saved_searches" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"search_key" text NOT NULL,
	"label" text DEFAULT '' NOT NULL,
	"q" text DEFAULT '' NOT NULL,
	"role" text DEFAULT '' NOT NULL,
	"location" text DEFAULT '' NOT NULL,
	"skills" text DEFAULT '' NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"seen_handles" text[] DEFAULT '{}'::text[] NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_checked_at" timestamp with time zone,
	"last_notified_at" timestamp with time zone,
	CONSTRAINT "cards_saved_searches_user_key" UNIQUE("user_id","search_key")
);
--> statement-breakpoint
ALTER TABLE "cards"."saved_searches" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."card_verifications" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"card_id" text NOT NULL,
	"provider" text NOT NULL,
	"verified_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_card_verifications_key" UNIQUE("card_id","provider"),
	CONSTRAINT "cards_card_verifications_provider_check" CHECK (provider IN ('linkedin', 'github', 'work_email'))
);
--> statement-breakpoint
ALTER TABLE "cards"."card_verifications" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."match_preferences" ADD CONSTRAINT "cards_match_preferences_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_reports" ADD CONSTRAINT "cards_card_reports_reporter_fkey" FOREIGN KEY ("reporter_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_reports" ADD CONSTRAINT "cards_card_reports_target_fkey" FOREIGN KEY ("target_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."saved_searches" ADD CONSTRAINT "cards_saved_searches_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_verifications" ADD CONSTRAINT "cards_card_verifications_card_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "cards_match_preferences_user_idx" ON "cards"."match_preferences" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "cards_card_reports_open_key" ON "cards"."card_reports" USING btree ("reporter_user_id","target_card_id") WHERE status = 'open';--> statement-breakpoint
CREATE INDEX "cards_card_reports_target_idx" ON "cards"."card_reports" USING btree ("target_card_id","status");--> statement-breakpoint
CREATE INDEX "cards_saved_searches_active_idx" ON "cards"."saved_searches" USING btree ("active","last_checked_at");--> statement-breakpoint
CREATE POLICY "service role full access on match_preferences" ON "cards"."match_preferences" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on card_reports" ON "cards"."card_reports" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on saved_searches" ON "cards"."saved_searches" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on card_verifications" ON "cards"."card_verifications" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);