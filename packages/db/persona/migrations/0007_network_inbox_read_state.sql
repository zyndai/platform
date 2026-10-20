-- owner: persona
-- Read state + inbox summaries for DMs and groups. Expand-only; no data is deleted.
-- Rollback: drop dm_thread_reads, persona_group_reads, the six summary columns, and the new indexes.
CREATE TABLE "dm_thread_reads" (
	"thread_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"last_read_at" timestamp with time zone DEFAULT now() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "dm_thread_reads_thread_id_user_id_pk" PRIMARY KEY("thread_id","user_id")
);
--> statement-breakpoint
ALTER TABLE "dm_thread_reads" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_group_reads" (
	"group_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"last_read_at" timestamp with time zone DEFAULT now() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "persona_group_reads_group_id_user_id_pk" PRIMARY KEY("group_id","user_id")
);
--> statement-breakpoint
ALTER TABLE "persona_group_reads" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "dm_threads" ADD COLUMN "last_message_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "dm_threads" ADD COLUMN "last_message_preview" text;--> statement-breakpoint
ALTER TABLE "dm_threads" ADD COLUMN "last_message_sender_id" text;--> statement-breakpoint
ALTER TABLE "persona_groups" ADD COLUMN "last_message_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "persona_groups" ADD COLUMN "last_message_preview" text;--> statement-breakpoint
ALTER TABLE "persona_groups" ADD COLUMN "last_message_sender_name" text;--> statement-breakpoint
ALTER TABLE "dm_thread_reads" ADD CONSTRAINT "dm_thread_reads_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "dm_thread_reads" ADD CONSTRAINT "dm_thread_reads_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_reads" ADD CONSTRAINT "persona_group_reads_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_reads" ADD CONSTRAINT "persona_group_reads_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "dm_thread_reads_user_idx" ON "dm_thread_reads" USING btree ("user_id","updated_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "persona_group_reads_user_idx" ON "persona_group_reads" USING btree ("user_id","updated_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "dm_messages_thread_created_idx" ON "dm_messages" USING btree ("thread_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "dm_threads_initiator_updated_idx" ON "dm_threads" USING btree ("initiator_id","updated_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "dm_threads_receiver_updated_idx" ON "dm_threads" USING btree ("receiver_id","updated_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "persona_group_messages_group_created_id_idx" ON "persona_group_messages" USING btree ("group_id","created_at" DESC NULLS FIRST,"id" DESC NULLS LAST);--> statement-breakpoint
CREATE POLICY "Service role full access on dm_thread_reads" ON "dm_thread_reads" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "service role full access on persona_group_reads" ON "persona_group_reads" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));