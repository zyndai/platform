-- owner: persona
-- 0000 — BASELINE of the aafo public schema as it was on 2026-09-26.
--
-- !! NEVER RUN THIS ON PROD. Prod already has all of it; it is recorded as
-- !! applied with `npm run db:baseline-sql` (see README.md). It runs only on
-- !! fresh databases (CI, local scratch) to rebuild the same schema.
--
-- Tables, constraints, indexes, RLS and policies below are drizzle-kit's
-- output for persona/schema/*.ts. Functions, grants, the trigger and the
-- realtime publication are hand-written (Drizzle doesn't model them), copied
-- from prod's catalog. Proof that this matches prod: `npm run db:drift`.

CREATE TABLE "persona_agents" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"agent_id" text NOT NULL,
	"derivation_index" integer NOT NULL,
	"public_key" text NOT NULL,
	"name" text NOT NULL,
	"agent_handle" text,
	"description" text DEFAULT '' NOT NULL,
	"capabilities" jsonb DEFAULT '[]'::jsonb,
	"profile" jsonb DEFAULT '{}'::jsonb,
	"webhook_url" text,
	"active" boolean DEFAULT true,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	"brief_doc_id" text,
	"brief_doc_url" text,
	"brief_doc_revision_id" text,
	"brief_content" text,
	"search_vector" "tsvector",
	"auto_extract_todos" boolean DEFAULT true NOT NULL,
	CONSTRAINT "persona_agents_agent_id_key" UNIQUE("agent_id"),
	CONSTRAINT "persona_agents_derivation_index_key" UNIQUE("derivation_index")
);
--> statement-breakpoint
ALTER TABLE "persona_agents" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "callback_results" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"callback_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"thread_id" uuid NOT NULL,
	"peer_agent_id" text NOT NULL,
	"task_state" text NOT NULL,
	"reply_text" text,
	"raw_event" jsonb NOT NULL,
	"delivered_to_ui" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "callback_results_callback_id_key" UNIQUE("callback_id")
);
--> statement-breakpoint
ALTER TABLE "callback_results" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "outbound_callbacks" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"thread_id" uuid NOT NULL,
	"peer_agent_id" text NOT NULL,
	"peer_task_id" text,
	"our_message_id" text NOT NULL,
	"origin_kind" text NOT NULL,
	"origin_ref" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"push_token" text NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"expires_at" timestamp with time zone DEFAULT (now() + '24:00:00'::interval) NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	"peer_a2a_url" text,
	"last_state" text,
	"last_event" jsonb,
	"last_event_at" timestamp with time zone,
	"answer_text" text,
	"terminal_state" text,
	CONSTRAINT "outbound_callbacks_push_token_key" UNIQUE("push_token"),
	CONSTRAINT "outbound_callbacks_status_check" CHECK (status IN ('pending', 'received', 'expired', 'failed'))
);
--> statement-breakpoint
ALTER TABLE "outbound_callbacks" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "enriched_companies" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"cache_key" text NOT NULL,
	"company_name" text,
	"company_url" text,
	"linkedin_url" text,
	"industry" text,
	"employee_count" text,
	"revenue" text,
	"city" text,
	"region_code" text,
	"country_code" text,
	"data" jsonb DEFAULT '{}'::jsonb,
	"source" text,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "enriched_companies_user_id_cache_key_key" UNIQUE("user_id","cache_key")
);
--> statement-breakpoint
ALTER TABLE "enriched_companies" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "enriched_contacts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"cache_key" text NOT NULL,
	"employee_linkedin" text,
	"email" text,
	"first_name" text,
	"last_name" text,
	"title" text,
	"company_name" text,
	"company_url" text,
	"phone" text,
	"phone_type" text,
	"has_email" boolean DEFAULT false,
	"has_phone" boolean DEFAULT false,
	"data" jsonb DEFAULT '{}'::jsonb,
	"source" text,
	"enriched_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "enriched_contacts_user_id_cache_key_key" UNIQUE("user_id","cache_key")
);
--> statement-breakpoint
ALTER TABLE "enriched_contacts" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "suggested_contact_runs" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"last_run_at" timestamp with time zone,
	"last_manual_at" timestamp with time zone,
	"status" text,
	"detail" text,
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE "suggested_contact_runs" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "suggested_contacts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"cache_key" text NOT NULL,
	"recipe" text NOT NULL,
	"reason" text,
	"score" real DEFAULT 0,
	"rank" integer DEFAULT 0,
	"generated_at" timestamp with time zone DEFAULT now(),
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "suggested_contacts_user_id_cache_key_recipe_key" UNIQUE("user_id","cache_key","recipe")
);
--> statement-breakpoint
ALTER TABLE "suggested_contacts" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "brief_todos" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"title" text NOT NULL,
	"source_text" text,
	"done" boolean DEFAULT false NOT NULL,
	"done_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"group_id" uuid,
	"assigned_by_user_id" uuid
);
--> statement-breakpoint
ALTER TABLE "brief_todos" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "chat_messages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"conversation_id" text NOT NULL,
	"role" text NOT NULL,
	"content" text NOT NULL,
	"actions" jsonb DEFAULT '[]'::jsonb,
	"created_at" timestamp with time zone DEFAULT now(),
	"action_summary" jsonb DEFAULT '[]'::jsonb
);
--> statement-breakpoint
ALTER TABLE "chat_messages" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "published_pages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"slug" text NOT NULL,
	"title" text NOT NULL,
	"format" text NOT NULL,
	"content" text NOT NULL,
	"visibility" text DEFAULT 'unlisted' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	"expires_at" timestamp with time zone,
	CONSTRAINT "published_pages_slug_key" UNIQUE("slug"),
	CONSTRAINT "published_pages_format_check" CHECK (format IN ('html', 'markdown')),
	CONSTRAINT "published_pages_visibility_check" CHECK (visibility IN ('public', 'unlisted', 'private'))
);
--> statement-breakpoint
ALTER TABLE "published_pages" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "a2a_tasks" (
	"task_id" uuid PRIMARY KEY NOT NULL,
	"context_id" uuid NOT NULL,
	"state" text DEFAULT 'submitted' NOT NULL,
	"permission_snapshot" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"history" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"artifacts" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"push_url" text,
	"push_token" text,
	"last_message_id" text,
	"idle_ttl_ms" bigint DEFAULT 3600000 NOT NULL,
	"idle_until" timestamp with time zone,
	"terminal_at" timestamp with time zone,
	"failure_reason" text,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "a2a_tasks_state_check" CHECK (state IN ('submitted', 'working', 'input-required', 'auth-required', 'completed', 'canceled', 'failed', 'rejected'))
);
--> statement-breakpoint
ALTER TABLE "a2a_tasks" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "agent_tasks" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"thread_id" uuid NOT NULL,
	"type" text DEFAULT 'meeting' NOT NULL,
	"status" text DEFAULT 'proposed' NOT NULL,
	"initiator_user_id" uuid NOT NULL,
	"recipient_user_id" uuid NOT NULL,
	"initiator_agent_id" text NOT NULL,
	"recipient_agent_id" text NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"history" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"calendar_event_ids" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "agent_tasks_type_check" CHECK (type = 'meeting'),
	CONSTRAINT "agent_tasks_status_check" CHECK (status IN ('proposed', 'countered', 'accepted', 'scheduled', 'declined', 'cancelled', 'book_failed'))
);
--> statement-breakpoint
ALTER TABLE "agent_tasks" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "dm_messages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"thread_id" uuid NOT NULL,
	"sender_id" text NOT NULL,
	"sender_type" text DEFAULT 'human' NOT NULL,
	"channel" text DEFAULT 'human' NOT NULL,
	"content" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "dm_messages_sender_type_check" CHECK (sender_type IN ('human', 'agent', 'system')),
	CONSTRAINT "dm_messages_channel_check" CHECK (channel IN ('human', 'agent'))
);
--> statement-breakpoint
ALTER TABLE "dm_messages" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "dm_threads" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"initiator_id" text NOT NULL,
	"receiver_id" text NOT NULL,
	"initiator_name" text DEFAULT '',
	"receiver_name" text DEFAULT '',
	"status" text DEFAULT 'pending' NOT NULL,
	"lifecycle" text DEFAULT 'pending' NOT NULL,
	"initiator_mode" text DEFAULT 'agent' NOT NULL,
	"receiver_mode" text DEFAULT 'agent' NOT NULL,
	"permissions" jsonb DEFAULT jsonb_build_object('can_request_meetings', true, 'can_query_availability', false, 'can_view_full_profile', false, 'can_post_on_my_behalf', false) NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "dm_threads_initiator_id_receiver_id_key" UNIQUE("initiator_id","receiver_id"),
	CONSTRAINT "dm_threads_status_check" CHECK (status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked')),
	CONSTRAINT "dm_threads_initiator_mode_check" CHECK (initiator_mode IN ('human', 'agent')),
	CONSTRAINT "dm_threads_receiver_mode_check" CHECK (receiver_mode IN ('human', 'agent'))
);
--> statement-breakpoint
ALTER TABLE "dm_threads" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "pending_approvals" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"thread_id" uuid,
	"tool_name" text NOT NULL,
	"tool_args" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"summary" text,
	"status" text DEFAULT 'pending' NOT NULL,
	"result" jsonb,
	"created_at" timestamp with time zone DEFAULT now(),
	"decided_at" timestamp with time zone,
	"expires_at" timestamp with time zone DEFAULT (now() + '24:00:00'::interval),
	CONSTRAINT "pending_approvals_status_check" CHECK (status IN ('pending', 'approved', 'declined', 'expired'))
);
--> statement-breakpoint
ALTER TABLE "pending_approvals" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_group_audit_events" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"affected_user_id" uuid NOT NULL,
	"actor_user_id" uuid,
	"kind" text NOT NULL,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "persona_group_audit_events_kind_check" CHECK (kind IN ('brief_shared', 'calendar_queried'))
);
--> statement-breakpoint
ALTER TABLE "persona_group_audit_events" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_group_constraints" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"kind" text NOT NULL,
	"text" text NOT NULL,
	"created_by_user_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"archived_at" timestamp with time zone,
	CONSTRAINT "persona_group_constraints_kind_check" CHECK (kind IN ('fact', 'rule', 'voice')),
	CONSTRAINT "persona_group_constraints_text_check" CHECK ((length(text) >= 1) AND (length(text) <= 400))
);
--> statement-breakpoint
ALTER TABLE "persona_group_constraints" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_group_invitations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"invitee_user_id" uuid NOT NULL,
	"inviter_user_id" uuid,
	"invitee_role" text DEFAULT 'member' NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"message" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"decided_at" timestamp with time zone,
	"expires_at" timestamp with time zone DEFAULT (now() + '7 days'::interval) NOT NULL,
	CONSTRAINT "persona_group_invitations_invitee_role_check" CHECK (invitee_role IN ('admin', 'member')),
	CONSTRAINT "persona_group_invitations_status_check" CHECK (status IN ('pending', 'accepted', 'declined', 'revoked', 'expired'))
);
--> statement-breakpoint
ALTER TABLE "persona_group_invitations" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_group_members" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"agent_id" text,
	"role" text DEFAULT 'member' NOT NULL,
	"permissions" jsonb DEFAULT jsonb_build_object('can_see_brief', false, 'can_see_member_briefs', false, 'can_see_group_brief', true, 'can_query_calendar', false, 'can_post', true, 'can_invite', false, 'can_speak_for_group', false) NOT NULL,
	"invited_by" uuid,
	"joined_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "persona_group_members_group_id_user_id_key" UNIQUE("group_id","user_id"),
	CONSTRAINT "persona_group_members_role_check" CHECK (role IN ('owner', 'admin', 'member'))
);
--> statement-breakpoint
ALTER TABLE "persona_group_members" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_group_messages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"sender_user_id" uuid,
	"sender_agent_id" text,
	"sender_name" text,
	"channel" text DEFAULT 'human' NOT NULL,
	"content" text NOT NULL,
	"reply_to" uuid,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "persona_group_messages_channel_check" CHECK (channel IN ('human', 'agent', 'system', 'broadcast'))
);
--> statement-breakpoint
ALTER TABLE "persona_group_messages" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "persona_groups" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" text NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"avatar_url" text,
	"owner_user_id" uuid NOT NULL,
	"visibility" text DEFAULT 'private' NOT NULL,
	"invite_token" text,
	"group_seed_index" integer DEFAULT 0 NOT NULL,
	"archived_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"brief_doc_id" text,
	"brief_doc_url" text,
	"join_domain" text,
	CONSTRAINT "persona_groups_slug_key" UNIQUE("slug"),
	CONSTRAINT "persona_groups_invite_token_key" UNIQUE("invite_token"),
	CONSTRAINT "persona_groups_visibility_check" CHECK (visibility IN ('private', 'open'))
);
--> statement-breakpoint
ALTER TABLE "persona_groups" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "api_tokens" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" text NOT NULL,
	"access_token" text NOT NULL,
	"refresh_token" text,
	"expires_at" timestamp with time zone,
	"scopes" text,
	"raw_data" jsonb DEFAULT '{}'::jsonb,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "api_tokens_user_id_provider_key" UNIQUE("user_id","provider")
);
--> statement-breakpoint
ALTER TABLE "api_tokens" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "github_profiles" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"username" text,
	"raw_repos" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"skills" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"projects" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"synced_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE "github_profiles" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "linkedin_profiles" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"profile_url" text,
	"scraped_at" timestamp with time zone,
	"raw_profile" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"raw_posts" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE "linkedin_profiles" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "oauth_pending_state" (
	"state" text PRIMARY KEY NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" text NOT NULL,
	"code_verifier" text,
	"created_at" timestamp with time zone DEFAULT now(),
	"expires_at" timestamp with time zone DEFAULT (now() + '00:15:00'::interval)
);
--> statement-breakpoint
ALTER TABLE "oauth_pending_state" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "telegram_chat_history" (
	"conversation_id" text PRIMARY KEY NOT NULL,
	"user_id" uuid NOT NULL,
	"messages" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE "telegram_chat_history" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "telegram_links" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"chat_id" text NOT NULL,
	"linked_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "telegram_links_chat_id_key" UNIQUE("chat_id")
);
--> statement-breakpoint
ALTER TABLE "telegram_links" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "twitter_profiles" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"handle" text,
	"scraped_at" timestamp with time zone,
	"raw_tweets" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"facts" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE "twitter_profiles" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "persona_agents" ADD CONSTRAINT "persona_agents_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "callback_results" ADD CONSTRAINT "callback_results_callback_id_fkey" FOREIGN KEY ("callback_id") REFERENCES "public"."outbound_callbacks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "callback_results" ADD CONSTRAINT "callback_results_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "outbound_callbacks" ADD CONSTRAINT "outbound_callbacks_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "enriched_companies" ADD CONSTRAINT "enriched_companies_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "enriched_contacts" ADD CONSTRAINT "enriched_contacts_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "suggested_contact_runs" ADD CONSTRAINT "suggested_contact_runs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "suggested_contacts" ADD CONSTRAINT "suggested_contacts_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brief_todos" ADD CONSTRAINT "brief_todos_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brief_todos" ADD CONSTRAINT "brief_todos_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brief_todos" ADD CONSTRAINT "brief_todos_assigned_by_user_id_fkey" FOREIGN KEY ("assigned_by_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_messages" ADD CONSTRAINT "chat_messages_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD CONSTRAINT "a2a_tasks_context_id_fkey" FOREIGN KEY ("context_id") REFERENCES "public"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_tasks" ADD CONSTRAINT "agent_tasks_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_tasks" ADD CONSTRAINT "agent_tasks_initiator_user_id_fkey" FOREIGN KEY ("initiator_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_tasks" ADD CONSTRAINT "agent_tasks_recipient_user_id_fkey" FOREIGN KEY ("recipient_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "dm_messages" ADD CONSTRAINT "dm_messages_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "pending_approvals" ADD CONSTRAINT "pending_approvals_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "pending_approvals" ADD CONSTRAINT "pending_approvals_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_audit_events" ADD CONSTRAINT "persona_group_audit_events_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_audit_events" ADD CONSTRAINT "persona_group_audit_events_affected_user_id_fkey" FOREIGN KEY ("affected_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_audit_events" ADD CONSTRAINT "persona_group_audit_events_actor_user_id_fkey" FOREIGN KEY ("actor_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_constraints" ADD CONSTRAINT "persona_group_constraints_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_constraints" ADD CONSTRAINT "persona_group_constraints_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_invitations" ADD CONSTRAINT "persona_group_invitations_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_invitations" ADD CONSTRAINT "persona_group_invitations_invitee_user_id_fkey" FOREIGN KEY ("invitee_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_invitations" ADD CONSTRAINT "persona_group_invitations_inviter_user_id_fkey" FOREIGN KEY ("inviter_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_members" ADD CONSTRAINT "persona_group_members_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_members" ADD CONSTRAINT "persona_group_members_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_members" ADD CONSTRAINT "persona_group_members_invited_by_fkey" FOREIGN KEY ("invited_by") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_messages" ADD CONSTRAINT "persona_group_messages_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_messages" ADD CONSTRAINT "persona_group_messages_sender_user_id_fkey" FOREIGN KEY ("sender_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_group_messages" ADD CONSTRAINT "persona_group_messages_reply_to_fkey" FOREIGN KEY ("reply_to") REFERENCES "public"."persona_group_messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "persona_groups" ADD CONSTRAINT "persona_groups_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "api_tokens" ADD CONSTRAINT "api_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "github_profiles" ADD CONSTRAINT "github_profiles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "linkedin_profiles" ADD CONSTRAINT "linkedin_profiles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "oauth_pending_state" ADD CONSTRAINT "oauth_pending_state_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "telegram_chat_history" ADD CONSTRAINT "telegram_chat_history_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "telegram_links" ADD CONSTRAINT "telegram_links_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "twitter_profiles" ADD CONSTRAINT "twitter_profiles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "persona_agents_search_vector_idx" ON "persona_agents" USING gin ("search_vector");--> statement-breakpoint
CREATE INDEX "callback_results_thread_idx" ON "callback_results" USING btree ("thread_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "callback_results_user_idx" ON "callback_results" USING btree ("user_id","delivered_to_ui","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "outbound_callbacks_expires_idx" ON "outbound_callbacks" USING btree ("expires_at") WHERE status = 'pending';--> statement-breakpoint
CREATE INDEX "outbound_callbacks_peer_task_idx" ON "outbound_callbacks" USING btree ("peer_agent_id","peer_task_id") WHERE peer_task_id IS NOT NULL;--> statement-breakpoint
CREATE INDEX "outbound_callbacks_user_idx" ON "outbound_callbacks" USING btree ("user_id","status","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "enriched_companies_user_created_idx" ON "enriched_companies" USING btree ("user_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "enriched_contacts_user_created_idx" ON "enriched_contacts" USING btree ("user_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "enriched_contacts_user_email_idx" ON "enriched_contacts" USING btree ("user_id","email");--> statement-breakpoint
CREATE INDEX "enriched_contacts_user_linkedin_idx" ON "enriched_contacts" USING btree ("user_id","employee_linkedin");--> statement-breakpoint
CREATE INDEX "suggested_contacts_user_rank_idx" ON "suggested_contacts" USING btree ("user_id","recipe","rank");--> statement-breakpoint
CREATE INDEX "brief_todos_group_idx" ON "brief_todos" USING btree ("group_id");--> statement-breakpoint
CREATE INDEX "brief_todos_user_idx" ON "brief_todos" USING btree ("user_id","done","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE UNIQUE INDEX "brief_todos_user_title_uniq" ON "brief_todos" USING btree ("user_id","title") WHERE done = false;--> statement-breakpoint
CREATE INDEX "published_pages_expires_idx" ON "published_pages" USING btree ("expires_at") WHERE expires_at IS NOT NULL;--> statement-breakpoint
CREATE INDEX "published_pages_slug_idx" ON "published_pages" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "published_pages_user_idx" ON "published_pages" USING btree ("user_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "a2a_tasks_context_idx" ON "a2a_tasks" USING btree ("context_id","updated_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "a2a_tasks_state_idle_idx" ON "a2a_tasks" USING btree ("state","idle_until") WHERE state IN ('input-required', 'auth-required');--> statement-breakpoint
CREATE INDEX "agent_tasks_initiator_idx" ON "agent_tasks" USING btree ("initiator_user_id");--> statement-breakpoint
CREATE INDEX "agent_tasks_recipient_idx" ON "agent_tasks" USING btree ("recipient_user_id");--> statement-breakpoint
CREATE INDEX "agent_tasks_status_idx" ON "agent_tasks" USING btree ("status");--> statement-breakpoint
CREATE INDEX "agent_tasks_thread_idx" ON "agent_tasks" USING btree ("thread_id");--> statement-breakpoint
CREATE UNIQUE INDEX "agent_tasks_one_open_proposal" ON "agent_tasks" USING btree ("thread_id") WHERE status IN ('proposed', 'countered', 'accepted');--> statement-breakpoint
CREATE INDEX "dm_threads_lifecycle_idx" ON "dm_threads" USING btree ("lifecycle");--> statement-breakpoint
CREATE INDEX "pending_approvals_thread_idx" ON "pending_approvals" USING btree ("thread_id");--> statement-breakpoint
CREATE INDEX "pending_approvals_user_status_idx" ON "pending_approvals" USING btree ("user_id","status");--> statement-breakpoint
CREATE INDEX "persona_group_audit_events_affected_idx" ON "persona_group_audit_events" USING btree ("affected_user_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "persona_group_audit_events_group_idx" ON "persona_group_audit_events" USING btree ("group_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "persona_group_constraints_group_idx" ON "persona_group_constraints" USING btree ("group_id","archived_at" NULLS FIRST,"created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "persona_group_invitations_group_status_idx" ON "persona_group_invitations" USING btree ("group_id","status");--> statement-breakpoint
CREATE INDEX "persona_group_invitations_invitee_status_idx" ON "persona_group_invitations" USING btree ("invitee_user_id","status");--> statement-breakpoint
CREATE UNIQUE INDEX "persona_group_invitations_open_uniq" ON "persona_group_invitations" USING btree ("group_id","invitee_user_id") WHERE status = 'pending';--> statement-breakpoint
CREATE INDEX "persona_group_members_agent_idx" ON "persona_group_members" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "persona_group_members_user_idx" ON "persona_group_members" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "persona_group_messages_group_idx" ON "persona_group_messages" USING btree ("group_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "persona_groups_join_domain_idx" ON "persona_groups" USING btree ("join_domain") WHERE (join_domain IS NOT NULL) AND (archived_at IS NULL);--> statement-breakpoint
CREATE INDEX "persona_groups_owner_idx" ON "persona_groups" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "github_profiles_synced_at_idx" ON "github_profiles" USING btree ("synced_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "linkedin_profiles_scraped_at_idx" ON "linkedin_profiles" USING btree ("scraped_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "telegram_chat_history_user_idx" ON "telegram_chat_history" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "telegram_links_chat_idx" ON "telegram_links" USING btree ("chat_id");--> statement-breakpoint
CREATE INDEX "twitter_profiles_scraped_at_idx" ON "twitter_profiles" USING btree ("scraped_at" DESC NULLS FIRST);--> statement-breakpoint
-- ── Functions (verbatim from prod aafo, 2026-09-26). They must exist before
--    the policies below that call is_persona_group_member/_manager.
CREATE OR REPLACE FUNCTION public.is_persona_group_manager(check_group_id uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
    SELECT auth.uid() IS NOT NULL
       AND EXISTS (
            SELECT 1
              FROM public.persona_group_members m
             WHERE m.group_id = check_group_id
               AND m.user_id = auth.uid()
               AND m.role IN ('owner', 'admin')
        );
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.is_persona_group_member(check_group_id uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
    SELECT auth.uid() IS NOT NULL
       AND EXISTS (
            SELECT 1
              FROM public.persona_group_members m
             WHERE m.group_id = check_group_id
               AND m.user_id = auth.uid()
        );
$function$;
--> statement-breakpoint
-- SECURITY DEFINER helpers: callable by the API roles, not by PUBLIC (as in prod).
REVOKE EXECUTE ON FUNCTION public.is_persona_group_manager(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.is_persona_group_member(uuid) FROM PUBLIC;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.persona_agents_search_vector_update()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
  caps_text      TEXT;
  interests_text TEXT;
BEGIN
  -- capabilities is a JSONB array of strings e.g. ["content writing", "fundraising"]
  SELECT COALESCE(string_agg(val, ' '), '')
  INTO caps_text
  FROM jsonb_array_elements_text(
    CASE WHEN jsonb_typeof(NEW.capabilities) = 'array'
         THEN NEW.capabilities
         ELSE '[]'::jsonb
    END
  ) AS val;

  -- profile->interests can be a JSON array or a comma-separated string
  IF jsonb_typeof(NEW.profile->'interests') = 'array' THEN
    SELECT COALESCE(string_agg(val, ' '), '')
    INTO interests_text
    FROM jsonb_array_elements_text(NEW.profile->'interests') AS val;
  ELSE
    interests_text := COALESCE(NEW.profile->>'interests', '');
  END IF;

  NEW.search_vector :=
    setweight(to_tsvector('english', COALESCE(NEW.name,                       '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(NEW.description,                '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(NEW.profile->>'title',          '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(NEW.profile->>'organization',   '')), 'C') ||
    setweight(to_tsvector('english', caps_text),                                    'C') ||
    setweight(to_tsvector('english', interests_text),                               'C') ||
    setweight(to_tsvector('english', COALESCE(NEW.brief_content,              '')), 'C');

  RETURN NEW;
END;
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.search_personas_fts(query_text text, result_limit integer DEFAULT 24)
 RETURNS TABLE(agent_id text, name text, description text)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
  RETURN QUERY
  SELECT
    pa.agent_id,
    pa.name,
    pa.description
  FROM persona_agents pa
  WHERE pa.active = TRUE
    AND pa.search_vector @@ plainto_tsquery('english', query_text)
  ORDER BY ts_rank(pa.search_vector, plainto_tsquery('english', query_text)) DESC
  LIMIT result_limit;
END;
$function$;
--> statement-breakpoint
CREATE POLICY "Service role full access on persona_agents" ON "persona_agents" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read own persona" ON "persona_agents" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users can update own persona" ON "persona_agents" AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Public read persona agents" ON "persona_agents" AS PERMISSIVE FOR SELECT TO public USING (true);--> statement-breakpoint
CREATE POLICY "Service role full access on callback_results" ON "callback_results" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Owner reads callback_results" ON "callback_results" AS PERMISSIVE FOR SELECT TO public USING ((user_id = auth.uid()));--> statement-breakpoint
CREATE POLICY "Owner marks delivered" ON "callback_results" AS PERMISSIVE FOR UPDATE TO public USING ((user_id = auth.uid())) WITH CHECK ((user_id = auth.uid()));--> statement-breakpoint
CREATE POLICY "Service role full access on outbound_callbacks" ON "outbound_callbacks" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Owner reads outbound_callbacks" ON "outbound_callbacks" AS PERMISSIVE FOR SELECT TO public USING ((user_id = auth.uid()));--> statement-breakpoint
CREATE POLICY "Service role full access on enriched_companies" ON "enriched_companies" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can CRUD own enriched companies" ON "enriched_companies" AS PERMISSIVE FOR ALL TO public USING ((auth.uid() = user_id)) WITH CHECK ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on enriched_contacts" ON "enriched_contacts" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can CRUD own enriched contacts" ON "enriched_contacts" AS PERMISSIVE FOR ALL TO public USING ((auth.uid() = user_id)) WITH CHECK ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on suggested_contact_runs" ON "suggested_contact_runs" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read own suggestion run state" ON "suggested_contact_runs" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on suggested_contacts" ON "suggested_contacts" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can CRUD own suggested contacts" ON "suggested_contacts" AS PERMISSIVE FOR ALL TO public USING ((auth.uid() = user_id)) WITH CHECK ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on brief_todos" ON "brief_todos" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read own brief todos" ON "brief_todos" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users can update own brief todos" ON "brief_todos" AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users can delete own brief todos" ON "brief_todos" AS PERMISSIVE FOR DELETE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Group members can read group todos" ON "brief_todos" AS PERMISSIVE FOR SELECT TO public USING ((group_id IS NOT NULL) AND is_persona_group_member(group_id));--> statement-breakpoint
CREATE POLICY "Service role full access on chat_messages" ON "chat_messages" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read own messages" ON "chat_messages" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on published_pages" ON "published_pages" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Public read for public pages" ON "published_pages" AS PERMISSIVE FOR SELECT TO public USING ((visibility = 'public'::text));--> statement-breakpoint
CREATE POLICY "Users can CRUD own pages" ON "published_pages" AS PERMISSIVE FOR ALL TO public USING ((auth.uid() = user_id)) WITH CHECK ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on a2a_tasks" ON "a2a_tasks" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Participants can read a2a_tasks" ON "a2a_tasks" AS PERMISSIVE FOR SELECT TO public USING (EXISTS ( SELECT 1
   FROM dm_threads t
  WHERE ((t.id = a2a_tasks.context_id) AND ((t.initiator_id = (auth.uid())::text) OR (t.receiver_id = (auth.uid())::text) OR (EXISTS ( SELECT 1
           FROM persona_agents p
          WHERE ((p.user_id = auth.uid()) AND ((p.agent_id = t.initiator_id) OR (p.agent_id = t.receiver_id)))))))));--> statement-breakpoint
CREATE POLICY "Service role full access on agent_tasks" ON "agent_tasks" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Participants can read agent_tasks" ON "agent_tasks" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = initiator_user_id) OR (auth.uid() = recipient_user_id));--> statement-breakpoint
CREATE POLICY "Participants can update agent_tasks" ON "agent_tasks" AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = initiator_user_id) OR (auth.uid() = recipient_user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on dm_messages" ON "dm_messages" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read messages in non-blocked threads" ON "dm_messages" AS PERMISSIVE FOR SELECT TO public USING (EXISTS ( SELECT 1
   FROM dm_threads t
  WHERE ((t.id = dm_messages.thread_id) AND ((t.initiator_id = (auth.uid())::text) OR (t.receiver_id = (auth.uid())::text) OR (EXISTS ( SELECT 1
           FROM persona_agents p
          WHERE ((p.user_id = auth.uid()) AND ((p.agent_id = t.initiator_id) OR (p.agent_id = t.receiver_id)))))) AND (t.status <> ALL (ARRAY['blocked'::text, 'revoked'::text])))));--> statement-breakpoint
CREATE POLICY "Users can send messages in accepted threads" ON "dm_messages" AS PERMISSIVE FOR INSERT TO public WITH CHECK ((((auth.uid())::text = sender_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND (persona_agents.agent_id = dm_messages.sender_id))))) AND (EXISTS ( SELECT 1
   FROM dm_threads t
  WHERE ((t.id = dm_messages.thread_id) AND ((t.initiator_id = (auth.uid())::text) OR (t.receiver_id = (auth.uid())::text) OR (EXISTS ( SELECT 1
           FROM persona_agents p
          WHERE ((p.user_id = auth.uid()) AND ((p.agent_id = t.initiator_id) OR (p.agent_id = t.receiver_id)))))) AND (t.status <> ALL (ARRAY['blocked'::text, 'declined'::text, 'revoked'::text]))))));--> statement-breakpoint
CREATE POLICY "Service role full access on dm_threads" ON "dm_threads" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read own threads" ON "dm_threads" AS PERMISSIVE FOR SELECT TO public USING (((auth.uid())::text = dm_threads.initiator_id) OR ((auth.uid())::text = dm_threads.receiver_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND ((persona_agents.agent_id = dm_threads.initiator_id) OR (persona_agents.agent_id = dm_threads.receiver_id))))));--> statement-breakpoint
CREATE POLICY "Participants can update threads" ON "dm_threads" AS PERMISSIVE FOR UPDATE TO public USING (((auth.uid())::text = dm_threads.initiator_id) OR ((auth.uid())::text = dm_threads.receiver_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND ((persona_agents.agent_id = dm_threads.initiator_id) OR (persona_agents.agent_id = dm_threads.receiver_id))))));--> statement-breakpoint
CREATE POLICY "Users can start threads" ON "dm_threads" AS PERMISSIVE FOR INSERT TO public WITH CHECK (((auth.uid())::text = initiator_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND (persona_agents.agent_id = dm_threads.initiator_id)))));--> statement-breakpoint
CREATE POLICY "Service role full access on pending_approvals" ON "pending_approvals" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users read own approvals" ON "pending_approvals" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users update own approvals" ON "pending_approvals" AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "service role full access on persona_group_audit_events" ON "persona_group_audit_events" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "affected user reads own audit events" ON "persona_group_audit_events" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = affected_user_id));--> statement-breakpoint
CREATE POLICY "owner reads group audit events" ON "persona_group_audit_events" AS PERMISSIVE FOR SELECT TO public USING (is_persona_group_manager(group_id));--> statement-breakpoint
CREATE POLICY "service role full access on persona_group_constraints" ON "persona_group_constraints" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "members read group constraints" ON "persona_group_constraints" AS PERMISSIVE FOR SELECT TO public USING (is_persona_group_member(group_id));--> statement-breakpoint
CREATE POLICY "service role full access on persona_group_members" ON "persona_group_members" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "members read roster" ON "persona_group_members" AS PERMISSIVE FOR SELECT TO public USING (is_persona_group_member(group_id));--> statement-breakpoint
CREATE POLICY "service role full access on persona_group_messages" ON "persona_group_messages" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "members read messages" ON "persona_group_messages" AS PERMISSIVE FOR SELECT TO public USING (is_persona_group_member(group_id));--> statement-breakpoint
CREATE POLICY "service role full access on persona_groups" ON "persona_groups" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "members read group" ON "persona_groups" AS PERMISSIVE FOR SELECT TO public USING (is_persona_group_member(id));--> statement-breakpoint
CREATE POLICY "Service role full access on api_tokens" ON "api_tokens" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users can read own tokens" ON "api_tokens" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users can insert own tokens" ON "api_tokens" AS PERMISSIVE FOR INSERT TO public WITH CHECK ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users can update own tokens" ON "api_tokens" AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users can delete own tokens" ON "api_tokens" AS PERMISSIVE FOR DELETE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on github_profiles" ON "github_profiles" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users read own github profile" ON "github_profiles" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users delete own github profile" ON "github_profiles" AS PERMISSIVE FOR DELETE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on linkedin_profiles" ON "linkedin_profiles" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users read own linkedin profile" ON "linkedin_profiles" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users delete own linkedin profile" ON "linkedin_profiles" AS PERMISSIVE FOR DELETE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on telegram_chat_history" ON "telegram_chat_history" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users read own telegram history" ON "telegram_chat_history" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on telegram_links" ON "telegram_links" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users read own telegram link" ON "telegram_links" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users delete own telegram link" ON "telegram_links" AS PERMISSIVE FOR DELETE TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Service role full access on twitter_profiles" ON "twitter_profiles" AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));--> statement-breakpoint
CREATE POLICY "Users read own twitter profile" ON "twitter_profiles" AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));--> statement-breakpoint
CREATE POLICY "Users delete own twitter profile" ON "twitter_profiles" AS PERMISSIVE FOR DELETE TO public USING ((auth.uid() = user_id));
--> statement-breakpoint
-- ── Trigger, realtime publication (verbatim from prod aafo, 2026-09-26).
CREATE TRIGGER persona_agents_search_vector_trigger BEFORE INSERT OR UPDATE ON public.persona_agents FOR EACH ROW EXECUTE FUNCTION persona_agents_search_vector_update();
--> statement-breakpoint
ALTER PUBLICATION supabase_realtime ADD TABLE
  public.a2a_tasks,
  public.agent_tasks,
  public.callback_results,
  public.dm_messages,
  public.dm_threads,
  public.outbound_callbacks,
  public.pending_approvals,
  public.persona_group_invitations,
  public.persona_group_messages;
