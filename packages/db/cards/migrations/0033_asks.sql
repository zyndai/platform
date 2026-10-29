-- owner: cards
-- Asks (docs/plans/ZYND_ASKS_PLAN.md). A beacon becomes an ask: asks holds each posted ask (id = the id in
-- the card's beacon JSON) with how it ended and its outcome; ask_routes the people it was routed to (their
-- feed boost and one digest line); ask_offers who offered help through a feed reply, and whether the asker
-- credited them (credit shows on the helper's card until the helper hides it). Expand-only: three new
-- tables, nothing existing changes. Service-role only (RLS on, like card_events). Until they exist
-- cards-api quietly switches the asks features off (it detects the missing relation once and logs it), so
-- this can be applied before or after the deploy. Needs a human (AGENTS.md §6).
-- Rollback (after reverting cards-api, which stops reading and writing them):
--   DROP TABLE cards.ask_routes;
--   DROP TABLE cards.ask_offers;
--   DROP TABLE cards.asks;
CREATE TABLE "cards"."ask_offers" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"ask_id" uuid NOT NULL,
	"helper_user_id" uuid NOT NULL,
	"helper_card_id" text NOT NULL,
	"connection_id" uuid,
	"channel" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"credited_at" timestamp with time zone,
	"credit_hidden_at" timestamp with time zone,
	"credit_notified_at" timestamp with time zone,
	CONSTRAINT "ask_offers_channel_check" CHECK (channel IN ('dm', 'request'))
);
--> statement-breakpoint
ALTER TABLE "cards"."ask_offers" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."ask_routes" (
	"ask_id" uuid NOT NULL,
	"helper_card_id" text NOT NULL,
	"score" real NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"digest_sent_at" timestamp with time zone,
	CONSTRAINT "ask_routes_pkey" PRIMARY KEY("ask_id","helper_card_id")
);
--> statement-breakpoint
ALTER TABLE "cards"."ask_routes" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."asks" (
	"id" uuid PRIMARY KEY NOT NULL,
	"card_id" text NOT NULL,
	"owner_user_id" uuid,
	"text" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"ended_at" timestamp with time zone,
	"end_reason" text,
	"outcome" text,
	"outcome_at" timestamp with time zone,
	"outcome_prompted_at" timestamp with time zone,
	CONSTRAINT "asks_text_check" CHECK (char_length(text) BETWEEN 1 AND 280),
	CONSTRAINT "asks_end_reason_check" CHECK (end_reason IS NULL OR end_reason IN ('dismissed', 'replaced', 'solved')),
	CONSTRAINT "asks_outcome_check" CHECK (outcome IS NULL OR outcome IN ('helped', 'solved_elsewhere', 'still_looking'))
);
--> statement-breakpoint
ALTER TABLE "cards"."asks" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."ask_offers" ADD CONSTRAINT "ask_offers_ask_id_fkey" FOREIGN KEY ("ask_id") REFERENCES "cards"."asks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."ask_offers" ADD CONSTRAINT "ask_offers_helper_card_id_fkey" FOREIGN KEY ("helper_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."ask_routes" ADD CONSTRAINT "ask_routes_ask_id_fkey" FOREIGN KEY ("ask_id") REFERENCES "cards"."asks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."ask_routes" ADD CONSTRAINT "ask_routes_helper_card_id_fkey" FOREIGN KEY ("helper_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."asks" ADD CONSTRAINT "asks_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "ask_offers_ask_helper_key" ON "cards"."ask_offers" USING btree ("ask_id","helper_user_id");--> statement-breakpoint
CREATE INDEX "ask_offers_credited_idx" ON "cards"."ask_offers" USING btree ("helper_card_id") WHERE credited_at IS NOT NULL;--> statement-breakpoint
CREATE INDEX "ask_routes_helper_idx" ON "cards"."ask_routes" USING btree ("helper_card_id","digest_sent_at");--> statement-breakpoint
CREATE INDEX "asks_card_created_idx" ON "cards"."asks" USING btree ("card_id","created_at" DESC NULLS LAST);--> statement-breakpoint
CREATE POLICY "service role full access on ask_offers" ON "cards"."ask_offers" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on ask_routes" ON "cards"."ask_routes" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on asks" ON "cards"."asks" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);