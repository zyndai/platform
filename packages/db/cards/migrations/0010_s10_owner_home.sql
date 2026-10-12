-- owner: cards
-- S10 persistent notifications, preferences, and non-destructive merge audit.
-- Rollback: disable FEATURE_S10_HOME / FEATURE_S10_DIGEST. Leave additive
-- columns/tables in place so archived URLs and audit records survive rollback.
CREATE TABLE "cards"."card_merges" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_email" text NOT NULL,
	"canonical_id" text NOT NULL,
	"archived_id" text NOT NULL,
	"snapshot" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_merges_archived_id_key" UNIQUE("archived_id")
);
--> statement-breakpoint
ALTER TABLE "cards"."card_merges" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."card_nudges" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_email" text NOT NULL,
	"handle" text NOT NULL,
	"dedupe_key" text NOT NULL,
	"kind" text NOT NULL,
	"title" text NOT NULL,
	"href" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"dismissed_at" timestamp with time zone,
	CONSTRAINT "card_nudges_owner_key" UNIQUE("owner_email","dedupe_key")
);
--> statement-breakpoint
ALTER TABLE "cards"."card_nudges" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."notification_deliveries" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_email" text NOT NULL,
	"kind" text NOT NULL,
	"period" text NOT NULL,
	"status" text DEFAULT 'claimed' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"sent_at" timestamp with time zone,
	CONSTRAINT "notification_deliveries_owner_period" UNIQUE("owner_email","kind","period")
);
--> statement-breakpoint
ALTER TABLE "cards"."notification_deliveries" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "notification_prefs" jsonb DEFAULT '{"weekly_digest":true,"email_nudges":false}'::jsonb NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "unsubscribe_token" uuid DEFAULT gen_random_uuid() NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "merged_into" text;--> statement-breakpoint
CREATE INDEX "card_merges_canonical_idx" ON "cards"."card_merges" USING btree ("canonical_id");--> statement-breakpoint
CREATE INDEX "card_nudges_owner_created_idx" ON "cards"."card_nudges" USING btree ("owner_email","created_at");--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD CONSTRAINT "agent_profile_cards_unsubscribe_token_key" UNIQUE("unsubscribe_token");--> statement-breakpoint
CREATE POLICY "service role full access on card_merges" ON "cards"."card_merges" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on card_nudges" ON "cards"."card_nudges" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on notification_deliveries" ON "cards"."notification_deliveries" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);
