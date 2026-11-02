-- owner: cards
-- Keep dated, owner-confirmed milestones and private recap snapshots so monthly claims
-- do not depend on a mutable profile or an approximate heatmap. Service-role access only.
-- Rollback (after code rollback, human approval required):
-- DROP TABLE cards.card_recaps; DROP TABLE cards.card_milestones;
CREATE TABLE "cards"."card_milestones" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"card_id" text NOT NULL,
	"owner_email" text NOT NULL,
	"kind" text NOT NULL,
	"title" text NOT NULL,
	"url" text DEFAULT '' NOT NULL,
	"occurred_on" date NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_milestones_dedupe" UNIQUE("card_id","owner_email","kind","title","occurred_on"),
	CONSTRAINT "card_milestones_kind_check" CHECK ("cards"."card_milestones"."kind" IN ('shipped', 'learned')),
	CONSTRAINT "card_milestones_title_check" CHECK (char_length("cards"."card_milestones"."title") BETWEEN 1 AND 140)
);
--> statement-breakpoint
ALTER TABLE "cards"."card_milestones" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."card_recaps" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"card_id" text NOT NULL,
	"owner_email" text NOT NULL,
	"period" text NOT NULL,
	"snapshot" jsonb NOT NULL,
	"selected_ids" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"caption" text DEFAULT '' NOT NULL,
	"published_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_recaps_card_period" UNIQUE("card_id","owner_email","period"),
	CONSTRAINT "card_recaps_period_check" CHECK ("cards"."card_recaps"."period" ~ '^[0-9]{4}-(0[1-9]|1[0-2]|Q[1-4])$'),
	CONSTRAINT "card_recaps_caption_check" CHECK (char_length("cards"."card_recaps"."caption") <= 2000)
);
--> statement-breakpoint
ALTER TABLE "cards"."card_recaps" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."card_milestones" ADD CONSTRAINT "card_milestones_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."card_recaps" ADD CONSTRAINT "card_recaps_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "card_milestones_period_idx" ON "cards"."card_milestones" USING btree ("card_id","occurred_on");--> statement-breakpoint
CREATE INDEX "card_recaps_owner_idx" ON "cards"."card_recaps" USING btree ("owner_email","created_at");--> statement-breakpoint
CREATE POLICY "service role full access on card_milestones" ON "cards"."card_milestones" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on card_recaps" ON "cards"."card_recaps" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);
