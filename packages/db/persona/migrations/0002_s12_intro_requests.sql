-- owner: persona
-- S12 keeps decisions in Persona; no existing data is deleted.
-- Rollback: disable FEATURE_S12_INTROS; retain requests and audits.
CREATE TABLE "persona_intro_audit" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"intro_id" uuid,
	"actor_uid" uuid NOT NULL,
	"owner_uid" uuid NOT NULL,
	"action" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "persona_intro_audit" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_intro_rules" (
	"owner_uid" uuid NOT NULL,
	"requester_uid" uuid NOT NULL,
	"rule" text NOT NULL,
	CONSTRAINT "persona_intro_rules_owner_requester" UNIQUE("owner_uid","requester_uid"),
	CONSTRAINT "persona_intro_rule_check" CHECK (rule IN ('allow', 'deny'))
);
--> statement-breakpoint
ALTER TABLE "persona_intro_rules" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_intro_requests" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"card_id" text NOT NULL,
	"handle" text NOT NULL,
	"requester_uid" uuid NOT NULL,
	"owner_uid" uuid NOT NULL,
	"requester_agent_id" text NOT NULL,
	"owner_agent_id" text NOT NULL,
	"requester_name" text NOT NULL,
	"owner_name" text NOT NULL,
	"why" text NOT NULL,
	"asks" jsonb NOT NULL,
	"permissions" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"idempotency_key" uuid NOT NULL,
	"thread_id" uuid NOT NULL,
	"meeting_task_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"decided_at" timestamp with time zone,
	CONSTRAINT "persona_intro_requester_key" UNIQUE("requester_uid","idempotency_key"),
	CONSTRAINT "persona_intro_thread_key" UNIQUE("thread_id"),
	CONSTRAINT "persona_intro_status_check" CHECK (status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked')),
	CONSTRAINT "persona_intro_not_self" CHECK (requester_uid <> owner_uid)
);
--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "persona_intro_audit" ADD CONSTRAINT "persona_intro_audit_request_fkey" FOREIGN KEY ("intro_id") REFERENCES "public"."persona_intro_requests"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_rules" ADD CONSTRAINT "persona_intro_rule_owner_fkey" FOREIGN KEY ("owner_uid") REFERENCES "auth"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_rules" ADD CONSTRAINT "persona_intro_rule_requester_fkey" FOREIGN KEY ("requester_uid") REFERENCES "auth"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_requester_fkey" FOREIGN KEY ("requester_uid") REFERENCES "auth"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_owner_fkey" FOREIGN KEY ("owner_uid") REFERENCES "auth"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_thread_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_meeting_fkey" FOREIGN KEY ("meeting_task_id") REFERENCES "public"."agent_tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "persona_intro_audit_request_idx" ON "persona_intro_audit" USING btree ("intro_id");--> statement-breakpoint
CREATE INDEX "persona_intro_owner_created_idx" ON "persona_intro_requests" USING btree ("owner_uid","created_at");--> statement-breakpoint
CREATE INDEX "persona_intro_requester_created_idx" ON "persona_intro_requests" USING btree ("requester_uid","created_at");--> statement-breakpoint
CREATE POLICY "Service role full access on persona_intro_audit" ON "persona_intro_audit" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Service role full access on persona_intro_rules" ON "persona_intro_rules" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Service role full access on persona_intro_requests" ON "persona_intro_requests" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Intro participants read requests" ON "persona_intro_requests" AS PERMISSIVE FOR SELECT TO public USING (auth.uid() IN (requester_uid, owner_uid));
