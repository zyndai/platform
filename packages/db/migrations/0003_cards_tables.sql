-- owner: cards
-- The cards tables, moved from xmfj (dashboard project) with prod's exact columns,
-- plus owner_user_id → auth.users (the link between a card and its persona user).
-- Service role only: no anon read policy (see src/schema/cards/cards.ts).
CREATE TABLE "agent_profile_cards" (
	"id" text PRIMARY KEY NOT NULL,
	"status" text DEFAULT 'draft' NOT NULL,
	"handle_github" text,
	"handle_x" text,
	"card" jsonb NOT NULL,
	"search_tsv" "tsvector" GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((((((COALESCE(((card -> 'identity'::text) ->> 'name'::text), ''::text) || ' '::text) || COALESCE(((card -> 'identity'::text) ->> 'headline'::text), ''::text)) || ' '::text) || COALESCE((card ->> 'summary'::text), ''::text)) || ' '::text) || skill_names(card)))) STORED,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"published_at" timestamp with time zone,
	"handle" text,
	"embedding" vector(1536),
	"scrape_raw" jsonb,
	"user_intent" jsonb,
	"owner_email" text,
	"suggested_posts" jsonb,
	"claim_token_hash" text,
	"owner_user_id" uuid,
	CONSTRAINT "agent_profile_cards_handle_key" UNIQUE("handle")
);
--> statement-breakpoint
ALTER TABLE "agent_profile_cards" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "x_accounts" (
	"x_user_id" text PRIMARY KEY NOT NULL,
	"username" text NOT NULL,
	"card_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "x_accounts" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "x_conversations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"x_user_id" text NOT NULL,
	"card_id" text,
	"status" text DEFAULT 'initial' NOT NULL,
	"current_question" text,
	"answered" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "x_conversations" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "x_mentions" (
	"tweet_id" text PRIMARY KEY NOT NULL,
	"x_user_id" text NOT NULL,
	"text" text,
	"status" text DEFAULT 'processed' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "x_mentions" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "agent_profile_cards" ADD CONSTRAINT "agent_profile_cards_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "x_accounts" ADD CONSTRAINT "x_accounts_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "public"."agent_profile_cards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "x_conversations" ADD CONSTRAINT "x_conversations_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "public"."agent_profile_cards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "agent_profile_cards_status_idx" ON "agent_profile_cards" USING btree ("status");--> statement-breakpoint
CREATE INDEX "agent_profile_cards_tsv_idx" ON "agent_profile_cards" USING gin ("search_tsv");--> statement-breakpoint
CREATE INDEX "agent_profile_cards_embedding_hnsw_idx" ON "agent_profile_cards" USING hnsw ("embedding" vector_cosine_ops);--> statement-breakpoint
CREATE INDEX "idx_cards_owner_email" ON "agent_profile_cards" USING btree ("owner_email");--> statement-breakpoint
CREATE INDEX "agent_profile_cards_owner_user_id_idx" ON "agent_profile_cards" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "x_conversations_user_idx" ON "x_conversations" USING btree ("x_user_id");--> statement-breakpoint
CREATE INDEX "x_mentions_user_idx" ON "x_mentions" USING btree ("x_user_id");--> statement-breakpoint
CREATE POLICY "service role full access on cards" ON "agent_profile_cards" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on x_accounts" ON "x_accounts" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on x_conversations" ON "x_conversations" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on x_mentions" ON "x_mentions" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);