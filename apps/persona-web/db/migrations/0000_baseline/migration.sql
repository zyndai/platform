-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "auth";

-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "public"."ApiProvider" AS ENUM ('linkedin', 'twitter', 'google', 'notion');

-- CreateEnum
CREATE TYPE "public"."ChatRole" AS ENUM ('user', 'assistant');

-- CreateEnum
CREATE TYPE "public"."DmThreadStatus" AS ENUM ('pending', 'accepted', 'declined', 'blocked', 'revoked');

-- CreateEnum
CREATE TYPE "public"."DmMode" AS ENUM ('human', 'agent');

-- CreateEnum
CREATE TYPE "public"."DmSenderType" AS ENUM ('human', 'agent', 'system');

-- CreateEnum
CREATE TYPE "public"."DmChannel" AS ENUM ('human', 'agent');

-- CreateEnum
CREATE TYPE "public"."AgentTaskType" AS ENUM ('meeting');

-- CreateEnum
CREATE TYPE "public"."AgentTaskStatus" AS ENUM ('proposed', 'countered', 'accepted', 'scheduled', 'declined', 'cancelled', 'book_failed');

-- CreateEnum
CREATE TYPE "public"."A2ATaskState" AS ENUM ('submitted', 'working', 'input-required', 'auth-required', 'completed', 'canceled', 'failed', 'rejected');

-- CreateEnum
CREATE TYPE "public"."ApprovalStatus" AS ENUM ('pending', 'approved', 'declined', 'expired');

-- CreateEnum
CREATE TYPE "public"."CallbackStatus" AS ENUM ('pending', 'received', 'expired', 'failed');

-- CreateEnum
CREATE TYPE "public"."GroupVisibility" AS ENUM ('private', 'open');

-- CreateEnum
CREATE TYPE "public"."GroupMemberRole" AS ENUM ('owner', 'admin', 'member');

-- CreateEnum
CREATE TYPE "public"."GroupMessageChannel" AS ENUM ('human', 'agent', 'system', 'broadcast');

-- CreateEnum
CREATE TYPE "public"."GroupConstraintKind" AS ENUM ('fact', 'rule', 'voice');

-- CreateEnum
CREATE TYPE "public"."GroupAuditKind" AS ENUM ('brief_shared', 'calendar_queried');

-- ────────────────────────────────────────────────────────────────────
-- auth.users is owned and managed by Supabase. Prisma's generated
-- baseline includes a CREATE TABLE for it because the schema models
-- the reference; we intentionally STRIP it here so this baseline can
-- be applied to a Supabase project without conflicting with the
-- pre-existing auth.users table. The schemas[] in schema.prisma keeps
-- the FK references intact.
-- ────────────────────────────────────────────────────────────────────
-- (auth.users CREATE TABLE block removed — managed by Supabase)

-- CreateTable
CREATE TABLE "public"."api_tokens" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "provider" "public"."ApiProvider" NOT NULL,
    "access_token" TEXT NOT NULL,
    "refresh_token" TEXT,
    "expires_at" TIMESTAMPTZ,
    "scopes" TEXT,
    "raw_data" JSONB NOT NULL DEFAULT '{}',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "api_tokens_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."chat_messages" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "conversation_id" TEXT NOT NULL,
    "role" "public"."ChatRole" NOT NULL,
    "content" TEXT NOT NULL,
    "actions" JSONB NOT NULL DEFAULT '[]',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "chat_messages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."persona_agents" (
    "user_id" UUID NOT NULL,
    "agent_id" TEXT NOT NULL,
    "derivation_index" INTEGER NOT NULL,
    "public_key" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "agent_handle" TEXT,
    "description" TEXT NOT NULL DEFAULT '',
    "capabilities" JSONB NOT NULL DEFAULT '[]',
    "profile" JSONB NOT NULL DEFAULT '{}',
    "webhook_url" TEXT,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "brief_doc_id" TEXT,
    "brief_doc_url" TEXT,
    "brief_doc_revision_id" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "persona_agents_pkey" PRIMARY KEY ("user_id")
);

-- CreateTable
CREATE TABLE "public"."dm_threads" (
    "id" UUID NOT NULL,
    "initiator_id" TEXT NOT NULL,
    "receiver_id" TEXT NOT NULL,
    "initiator_name" TEXT NOT NULL DEFAULT '',
    "receiver_name" TEXT NOT NULL DEFAULT '',
    "status" "public"."DmThreadStatus" NOT NULL DEFAULT 'pending',
    "lifecycle" TEXT NOT NULL DEFAULT 'pending',
    "initiator_mode" "public"."DmMode" NOT NULL DEFAULT 'agent',
    "receiver_mode" "public"."DmMode" NOT NULL DEFAULT 'agent',
    "permissions" JSONB NOT NULL DEFAULT '{"can_request_meetings": true, "can_query_availability": false, "can_view_full_profile": false, "can_post_on_my_behalf": false}',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "dm_threads_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."dm_messages" (
    "id" UUID NOT NULL,
    "thread_id" UUID NOT NULL,
    "sender_id" TEXT NOT NULL,
    "sender_type" "public"."DmSenderType" NOT NULL DEFAULT 'human',
    "channel" "public"."DmChannel" NOT NULL DEFAULT 'human',
    "content" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "dm_messages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."agent_tasks" (
    "id" UUID NOT NULL,
    "thread_id" UUID NOT NULL,
    "type" "public"."AgentTaskType" NOT NULL DEFAULT 'meeting',
    "status" "public"."AgentTaskStatus" NOT NULL DEFAULT 'proposed',
    "initiator_user_id" UUID NOT NULL,
    "recipient_user_id" UUID NOT NULL,
    "initiator_agent_id" TEXT NOT NULL,
    "recipient_agent_id" TEXT NOT NULL,
    "payload" JSONB NOT NULL DEFAULT '{}',
    "history" JSONB NOT NULL DEFAULT '[]',
    "calendar_event_ids" JSONB NOT NULL DEFAULT '{}',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "agent_tasks_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."a2a_tasks" (
    "task_id" UUID NOT NULL,
    "context_id" UUID NOT NULL,
    "state" "public"."A2ATaskState" NOT NULL DEFAULT 'submitted',
    "permission_snapshot" JSONB NOT NULL DEFAULT '{}',
    "history" JSONB NOT NULL DEFAULT '[]',
    "artifacts" JSONB NOT NULL DEFAULT '[]',
    "push_url" TEXT,
    "push_token" TEXT,
    "last_message_id" TEXT,
    "idle_ttl_ms" BIGINT NOT NULL DEFAULT 3600000,
    "idle_until" TIMESTAMPTZ,
    "terminal_at" TIMESTAMPTZ,
    "failure_reason" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "a2a_tasks_pkey" PRIMARY KEY ("task_id")
);

-- CreateTable
CREATE TABLE "public"."pending_approvals" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "thread_id" UUID,
    "tool_name" TEXT NOT NULL,
    "tool_args" JSONB NOT NULL DEFAULT '{}',
    "summary" TEXT,
    "status" "public"."ApprovalStatus" NOT NULL DEFAULT 'pending',
    "result" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "decided_at" TIMESTAMPTZ,
    "expires_at" TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours'),

    CONSTRAINT "pending_approvals_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."telegram_links" (
    "user_id" UUID NOT NULL,
    "chat_id" TEXT NOT NULL,
    "linked_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "telegram_links_pkey" PRIMARY KEY ("user_id")
);

-- CreateTable
CREATE TABLE "public"."telegram_chat_history" (
    "conversation_id" TEXT NOT NULL,
    "user_id" UUID NOT NULL,
    "messages" JSONB NOT NULL DEFAULT '[]',
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "telegram_chat_history_pkey" PRIMARY KEY ("conversation_id")
);

-- CreateTable
CREATE TABLE "public"."linkedin_profiles" (
    "user_id" UUID NOT NULL,
    "profile_url" TEXT,
    "scraped_at" TIMESTAMPTZ,
    "raw_profile" JSONB NOT NULL DEFAULT '{}',
    "raw_posts" JSONB NOT NULL DEFAULT '[]',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "linkedin_profiles_pkey" PRIMARY KEY ("user_id")
);

-- CreateTable
CREATE TABLE "public"."brief_todos" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "title" TEXT NOT NULL,
    "source_text" TEXT,
    "done" BOOLEAN NOT NULL DEFAULT false,
    "done_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "brief_todos_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."outbound_callbacks" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "thread_id" UUID NOT NULL,
    "peer_agent_id" TEXT NOT NULL,
    "peer_task_id" TEXT,
    "our_message_id" TEXT NOT NULL,
    "origin_kind" TEXT NOT NULL,
    "origin_ref" JSONB NOT NULL DEFAULT '{}',
    "push_token" TEXT NOT NULL,
    "status" "public"."CallbackStatus" NOT NULL DEFAULT 'pending',
    "expires_at" TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours'),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "outbound_callbacks_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."callback_results" (
    "id" UUID NOT NULL,
    "callback_id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "thread_id" UUID NOT NULL,
    "peer_agent_id" TEXT NOT NULL,
    "task_state" TEXT NOT NULL,
    "reply_text" TEXT,
    "raw_event" JSONB NOT NULL,
    "delivered_to_ui" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "callback_results_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."persona_groups" (
    "id" UUID NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "avatar_url" TEXT,
    "owner_user_id" UUID NOT NULL,
    "visibility" "public"."GroupVisibility" NOT NULL DEFAULT 'private',
    "invite_token" TEXT,
    "group_seed_index" INTEGER NOT NULL DEFAULT 0,
    "brief_doc_id" TEXT,
    "brief_doc_url" TEXT,
    "join_domain" TEXT,
    "archived_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "persona_groups_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."persona_group_members" (
    "id" UUID NOT NULL,
    "group_id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "agent_id" TEXT,
    "role" "public"."GroupMemberRole" NOT NULL DEFAULT 'member',
    "permissions" JSONB NOT NULL DEFAULT '{"can_see_brief": false, "can_query_calendar": false, "can_post": true, "can_invite": false, "can_speak_for_group": false}',
    "invited_by" UUID,
    "joined_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "persona_group_members_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."persona_group_messages" (
    "id" UUID NOT NULL,
    "group_id" UUID NOT NULL,
    "sender_user_id" UUID,
    "sender_agent_id" TEXT,
    "sender_name" TEXT,
    "channel" "public"."GroupMessageChannel" NOT NULL DEFAULT 'human',
    "content" TEXT NOT NULL,
    "reply_to" UUID,
    "metadata" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "persona_group_messages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."persona_group_constraints" (
    "id" UUID NOT NULL,
    "group_id" UUID NOT NULL,
    "kind" "public"."GroupConstraintKind" NOT NULL,
    "text" TEXT NOT NULL,
    "created_by_user_id" UUID,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "archived_at" TIMESTAMPTZ,

    CONSTRAINT "persona_group_constraints_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."persona_group_audit_events" (
    "id" UUID NOT NULL,
    "group_id" UUID NOT NULL,
    "affected_user_id" UUID NOT NULL,
    "actor_user_id" UUID,
    "kind" "public"."GroupAuditKind" NOT NULL,
    "metadata" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "persona_group_audit_events_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "api_tokens_user_id_provider_key" ON "public"."api_tokens"("user_id", "provider");

-- CreateIndex
CREATE INDEX "chat_messages_user_id_conversation_id_created_at_idx" ON "public"."chat_messages"("user_id", "conversation_id", "created_at");

-- CreateIndex
CREATE UNIQUE INDEX "persona_agents_agent_id_key" ON "public"."persona_agents"("agent_id");

-- CreateIndex
CREATE UNIQUE INDEX "persona_agents_derivation_index_key" ON "public"."persona_agents"("derivation_index");

-- CreateIndex
CREATE INDEX "dm_threads_lifecycle_idx" ON "public"."dm_threads"("lifecycle");

-- CreateIndex
CREATE UNIQUE INDEX "dm_threads_initiator_id_receiver_id_key" ON "public"."dm_threads"("initiator_id", "receiver_id");

-- CreateIndex
CREATE INDEX "dm_messages_thread_id_created_at_idx" ON "public"."dm_messages"("thread_id", "created_at");

-- CreateIndex
CREATE INDEX "agent_tasks_thread_id_idx" ON "public"."agent_tasks"("thread_id");

-- CreateIndex
CREATE INDEX "agent_tasks_initiator_user_id_idx" ON "public"."agent_tasks"("initiator_user_id");

-- CreateIndex
CREATE INDEX "agent_tasks_recipient_user_id_idx" ON "public"."agent_tasks"("recipient_user_id");

-- CreateIndex
CREATE INDEX "agent_tasks_status_idx" ON "public"."agent_tasks"("status");

-- CreateIndex
CREATE INDEX "a2a_tasks_context_id_updated_at_idx" ON "public"."a2a_tasks"("context_id", "updated_at");

-- CreateIndex
CREATE INDEX "pending_approvals_user_id_status_idx" ON "public"."pending_approvals"("user_id", "status");

-- CreateIndex
CREATE INDEX "pending_approvals_thread_id_idx" ON "public"."pending_approvals"("thread_id");

-- CreateIndex
CREATE UNIQUE INDEX "telegram_links_chat_id_key" ON "public"."telegram_links"("chat_id");

-- CreateIndex
CREATE INDEX "telegram_links_chat_id_idx" ON "public"."telegram_links"("chat_id");

-- CreateIndex
CREATE INDEX "telegram_chat_history_user_id_idx" ON "public"."telegram_chat_history"("user_id");

-- CreateIndex
CREATE INDEX "linkedin_profiles_scraped_at_idx" ON "public"."linkedin_profiles"("scraped_at" DESC);

-- CreateIndex
CREATE INDEX "brief_todos_user_id_done_created_at_idx" ON "public"."brief_todos"("user_id", "done", "created_at" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "outbound_callbacks_push_token_key" ON "public"."outbound_callbacks"("push_token");

-- CreateIndex
CREATE INDEX "outbound_callbacks_user_id_status_created_at_idx" ON "public"."outbound_callbacks"("user_id", "status", "created_at" DESC);

-- CreateIndex
CREATE INDEX "callback_results_user_id_delivered_to_ui_created_at_idx" ON "public"."callback_results"("user_id", "delivered_to_ui", "created_at" DESC);

-- CreateIndex
CREATE INDEX "callback_results_thread_id_created_at_idx" ON "public"."callback_results"("thread_id", "created_at" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "persona_groups_slug_key" ON "public"."persona_groups"("slug");

-- CreateIndex
CREATE UNIQUE INDEX "persona_groups_invite_token_key" ON "public"."persona_groups"("invite_token");

-- CreateIndex
CREATE INDEX "persona_groups_owner_user_id_idx" ON "public"."persona_groups"("owner_user_id");

-- CreateIndex
CREATE INDEX "persona_group_members_user_id_idx" ON "public"."persona_group_members"("user_id");

-- CreateIndex
CREATE INDEX "persona_group_members_agent_id_idx" ON "public"."persona_group_members"("agent_id");

-- CreateIndex
CREATE UNIQUE INDEX "persona_group_members_group_id_user_id_key" ON "public"."persona_group_members"("group_id", "user_id");

-- CreateIndex
CREATE INDEX "persona_group_messages_group_id_created_at_idx" ON "public"."persona_group_messages"("group_id", "created_at" DESC);

-- CreateIndex
CREATE INDEX "persona_group_audit_events_affected_user_id_created_at_idx" ON "public"."persona_group_audit_events"("affected_user_id", "created_at" DESC);

-- CreateIndex
CREATE INDEX "persona_group_audit_events_group_id_created_at_idx" ON "public"."persona_group_audit_events"("group_id", "created_at" DESC);

-- AddForeignKey
ALTER TABLE "public"."api_tokens" ADD CONSTRAINT "api_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."chat_messages" ADD CONSTRAINT "chat_messages_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_agents" ADD CONSTRAINT "persona_agents_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."dm_messages" ADD CONSTRAINT "dm_messages_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."agent_tasks" ADD CONSTRAINT "agent_tasks_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."agent_tasks" ADD CONSTRAINT "agent_tasks_initiator_user_id_fkey" FOREIGN KEY ("initiator_user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."agent_tasks" ADD CONSTRAINT "agent_tasks_recipient_user_id_fkey" FOREIGN KEY ("recipient_user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."a2a_tasks" ADD CONSTRAINT "a2a_tasks_context_id_fkey" FOREIGN KEY ("context_id") REFERENCES "public"."dm_threads"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."pending_approvals" ADD CONSTRAINT "pending_approvals_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."pending_approvals" ADD CONSTRAINT "pending_approvals_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."dm_threads"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."telegram_links" ADD CONSTRAINT "telegram_links_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."telegram_chat_history" ADD CONSTRAINT "telegram_chat_history_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."linkedin_profiles" ADD CONSTRAINT "linkedin_profiles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."brief_todos" ADD CONSTRAINT "brief_todos_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."outbound_callbacks" ADD CONSTRAINT "outbound_callbacks_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."callback_results" ADD CONSTRAINT "callback_results_callback_id_fkey" FOREIGN KEY ("callback_id") REFERENCES "public"."outbound_callbacks"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."callback_results" ADD CONSTRAINT "callback_results_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_groups" ADD CONSTRAINT "persona_groups_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_members" ADD CONSTRAINT "persona_group_members_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_members" ADD CONSTRAINT "persona_group_members_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_members" ADD CONSTRAINT "persona_group_members_invited_by_fkey" FOREIGN KEY ("invited_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_messages" ADD CONSTRAINT "persona_group_messages_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_messages" ADD CONSTRAINT "persona_group_messages_sender_user_id_fkey" FOREIGN KEY ("sender_user_id") REFERENCES "auth"."users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_messages" ADD CONSTRAINT "persona_group_messages_reply_to_fkey" FOREIGN KEY ("reply_to") REFERENCES "public"."persona_group_messages"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_constraints" ADD CONSTRAINT "persona_group_constraints_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_constraints" ADD CONSTRAINT "persona_group_constraints_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "auth"."users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_audit_events" ADD CONSTRAINT "persona_group_audit_events_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."persona_groups"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_audit_events" ADD CONSTRAINT "persona_group_audit_events_affected_user_id_fkey" FOREIGN KEY ("affected_user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "public"."persona_group_audit_events" ADD CONSTRAINT "persona_group_audit_events_actor_user_id_fkey" FOREIGN KEY ("actor_user_id") REFERENCES "auth"."users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

