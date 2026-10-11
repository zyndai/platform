-- owner: cards
-- S04: attribution columns on agent_profile_cards + card_events table.
-- Expand-only. Do not apply to prod without a human (AGENTS.md §6).
-- Rollback:
--   DROP POLICY IF EXISTS "service role full access on card_events" ON cards.card_events;
--   DROP INDEX IF EXISTS cards.card_events_handle_ts_idx;
--   DROP INDEX IF EXISTS cards.card_events_event_ts_idx;
--   ALTER TABLE cards.agent_profile_cards DROP COLUMN IF EXISTS created_via;
--   ALTER TABLE cards.agent_profile_cards DROP COLUMN IF EXISTS utm;
--   ALTER TABLE cards.agent_profile_cards DROP COLUMN IF EXISTS ref;
--   ALTER TABLE cards.agent_profile_cards DROP COLUMN IF EXISTS source;
--   DROP TABLE IF EXISTS cards.card_events;
CREATE TABLE "cards"."card_events" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"ts" timestamp with time zone DEFAULT now() NOT NULL,
	"event" text NOT NULL,
	"handle" text,
	"actor_class" text DEFAULT 'unknown' NOT NULL,
	"ref" text,
	"session_hash" text,
	"meta" jsonb,
	CONSTRAINT "card_events_actor_class_check" CHECK (actor_class IN ('human', 'ai_agent', 'search_bot', 'unknown'))
);
--> statement-breakpoint
ALTER TABLE "cards"."card_events" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "source" text;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "ref" text;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "utm" jsonb;--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "created_via" text;--> statement-breakpoint
CREATE INDEX "card_events_event_ts_idx" ON "cards"."card_events" USING btree ("event","ts");--> statement-breakpoint
CREATE INDEX "card_events_handle_ts_idx" ON "cards"."card_events" USING btree ("handle","ts");--> statement-breakpoint
CREATE POLICY "service role full access on card_events" ON "cards"."card_events" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);