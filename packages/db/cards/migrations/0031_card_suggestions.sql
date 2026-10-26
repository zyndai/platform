-- owner: cards
-- People search Phase 2: suggestions are searches run on a card owner's behalf. card_suggestions
-- holds each claimed card's top 20 people to meet, written nightly by cards-api
-- (POST /internal/suggestions/refresh); card_suggestion_impressions records who the digest and
-- owner home showed and what the owner did (hide, not relevant, connect), so the daily digest can
-- rotate people and dismissed people never come back. Expand-only: two new tables, nothing
-- existing changes. Service-role only. cards-api works without them (it computes live and records
-- nothing), so this can be applied before or after the deploy. Needs a human (AGENTS.md §6).
-- Rollback (after reverting cards-api, which stops reading and writing them):
--   DROP TABLE cards.card_suggestions, cards.card_suggestion_impressions;
CREATE TABLE "cards"."card_suggestion_impressions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"card_id" text NOT NULL,
	"candidate_card_id" text NOT NULL,
	"surface" text NOT NULL,
	"score" real,
	"shown_at" timestamp with time zone DEFAULT now() NOT NULL,
	"action" text,
	CONSTRAINT "card_suggestion_impressions_surface_check" CHECK (surface IN ('digest', 'owner_home', 'api')),
	CONSTRAINT "card_suggestion_impressions_action_check" CHECK (action IS NULL OR action IN ('viewed', 'connect', 'hide', 'not_relevant'))
);
--> statement-breakpoint
ALTER TABLE "cards"."card_suggestion_impressions" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."card_suggestions" (
	"card_id" text NOT NULL,
	"candidate_card_id" text NOT NULL,
	"target" text DEFAULT '' NOT NULL,
	"score" real NOT NULL,
	"why" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"two_way" boolean DEFAULT false NOT NULL,
	"computed_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_suggestions_pkey" PRIMARY KEY("card_id","candidate_card_id")
);
--> statement-breakpoint
ALTER TABLE "cards"."card_suggestions" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."card_suggestion_impressions" ADD CONSTRAINT "card_suggestion_impressions_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_suggestion_impressions" ADD CONSTRAINT "card_suggestion_impressions_candidate_card_id_fkey" FOREIGN KEY ("candidate_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_suggestions" ADD CONSTRAINT "card_suggestions_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_suggestions" ADD CONSTRAINT "card_suggestions_candidate_card_id_fkey" FOREIGN KEY ("candidate_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "card_suggestion_impressions_card_shown_idx" ON "cards"."card_suggestion_impressions" USING btree ("card_id","shown_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "card_suggestion_impressions_pair_idx" ON "cards"."card_suggestion_impressions" USING btree ("card_id","candidate_card_id");--> statement-breakpoint
CREATE POLICY "service role full access on card_suggestion_impressions" ON "cards"."card_suggestion_impressions" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on card_suggestions" ON "cards"."card_suggestions" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);