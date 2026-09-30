-- owner: cards
-- Shared daily cache of social posts per interest keyword. cards-api uses
-- this for GET /cards/by-handle/{handle}/suggested-posts so the same keyword
-- is fetched once per UTC day, not once per user.
-- Rollback: DROP TABLE IF EXISTS cards.keyword_posts;
CREATE TABLE "cards"."keyword_posts" (
	"keyword" text PRIMARY KEY NOT NULL,
	"fetched_on" date NOT NULL,
	"posts" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"summary" text DEFAULT '' NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."keyword_posts" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE POLICY "service role full access on keyword_posts" ON "cards"."keyword_posts" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);
