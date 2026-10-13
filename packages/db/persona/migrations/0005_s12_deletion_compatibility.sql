-- owner: persona
-- Keep new S12 records compatible with the existing explicit account/card deletion flow.
-- Replaces constraints on new S12 tables only; does not delete any data during migration.
-- Rollback: disable S12; retain these constraints to avoid blocking account deletion.
ALTER TABLE "persona_intro_audit" DROP CONSTRAINT "persona_intro_audit_request_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_rules" DROP CONSTRAINT "persona_intro_rule_owner_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_rules" DROP CONSTRAINT "persona_intro_rule_requester_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_requests" DROP CONSTRAINT "persona_intro_requester_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_requests" DROP CONSTRAINT "persona_intro_owner_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_requests" DROP CONSTRAINT "persona_intro_thread_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_requests" DROP CONSTRAINT "persona_intro_meeting_fkey";
--> statement-breakpoint
ALTER TABLE "persona_intro_audit" ADD CONSTRAINT "persona_intro_audit_request_fkey" FOREIGN KEY ("intro_id") REFERENCES "public"."persona_intro_requests"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_rules" ADD CONSTRAINT "persona_intro_rule_owner_fkey" FOREIGN KEY ("owner_uid") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_rules" ADD CONSTRAINT "persona_intro_rule_requester_fkey" FOREIGN KEY ("requester_uid") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_requester_fkey" FOREIGN KEY ("requester_uid") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_owner_fkey" FOREIGN KEY ("owner_uid") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_thread_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_intro_requests" ADD CONSTRAINT "persona_intro_meeting_fkey" FOREIGN KEY ("meeting_task_id") REFERENCES "public"."agent_tasks"("id") ON DELETE set null ON UPDATE no action;