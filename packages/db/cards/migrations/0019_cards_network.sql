-- owner: cards
-- Cards-native connection, DM, and group tables. API writes are service-role
-- only so verified-card ownership and invitation acceptance remain centralized.
-- Rollback: DROP TABLE cards.group_messages, cards.group_invitations,
-- cards.group_members, cards.groups, cards.dm_messages, cards.dm_threads,
-- cards.connections CASCADE;

CREATE TABLE "cards"."connections" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"connection_key" text NOT NULL,
	"requester_user_id" uuid NOT NULL,
	"requester_card_id" text NOT NULL,
	"recipient_user_id" uuid NOT NULL,
	"recipient_card_id" text NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"request_message" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"decided_at" timestamp with time zone,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_connections_key_key" UNIQUE("connection_key"),
	CONSTRAINT "cards_connections_status_check" CHECK (status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked'))
);
--> statement-breakpoint
ALTER TABLE "cards"."connections" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."dm_messages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"thread_id" uuid NOT NULL,
	"sender_user_id" uuid NOT NULL,
	"content" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."dm_messages" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."dm_threads" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"connection_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_dm_threads_connection_key" UNIQUE("connection_id")
);
--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_invitations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"invitee_user_id" uuid NOT NULL,
	"inviter_user_id" uuid NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"message" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"decided_at" timestamp with time zone,
	"expires_at" timestamp with time zone DEFAULT (now() + '7 days'::interval) NOT NULL,
	CONSTRAINT "cards_group_invitations_status_check" CHECK (status IN ('pending', 'accepted', 'declined', 'revoked', 'expired'))
);
--> statement-breakpoint
ALTER TABLE "cards"."group_invitations" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_members" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"role" text DEFAULT 'member' NOT NULL,
	"invited_by" uuid,
	"joined_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_group_members_group_user_key" UNIQUE("group_id","user_id"),
	CONSTRAINT "cards_group_members_role_check" CHECK (role IN ('owner', 'member'))
);
--> statement-breakpoint
ALTER TABLE "cards"."group_members" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_messages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"sender_user_id" uuid NOT NULL,
	"content" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."groups" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"owner_user_id" uuid NOT NULL,
	"visibility" text DEFAULT 'private' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"archived_at" timestamp with time zone,
	CONSTRAINT "cards_groups_visibility_check" CHECK (visibility IN ('private', 'open'))
);
--> statement-breakpoint
ALTER TABLE "cards"."groups" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."connections" ADD CONSTRAINT "cards_connections_requester_user_fkey" FOREIGN KEY ("requester_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."connections" ADD CONSTRAINT "cards_connections_requester_card_fkey" FOREIGN KEY ("requester_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."connections" ADD CONSTRAINT "cards_connections_recipient_user_fkey" FOREIGN KEY ("recipient_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."connections" ADD CONSTRAINT "cards_connections_recipient_card_fkey" FOREIGN KEY ("recipient_card_id") REFERENCES "cards"."agent_profile_cards"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."dm_messages" ADD CONSTRAINT "cards_dm_messages_thread_fkey" FOREIGN KEY ("thread_id") REFERENCES "cards"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."dm_messages" ADD CONSTRAINT "cards_dm_messages_sender_fkey" FOREIGN KEY ("sender_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD CONSTRAINT "cards_dm_threads_connection_fkey" FOREIGN KEY ("connection_id") REFERENCES "cards"."connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_invitations" ADD CONSTRAINT "cards_group_invitations_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_invitations" ADD CONSTRAINT "cards_group_invitations_invitee_fkey" FOREIGN KEY ("invitee_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_invitations" ADD CONSTRAINT "cards_group_invitations_inviter_fkey" FOREIGN KEY ("inviter_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_members" ADD CONSTRAINT "cards_group_members_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_members" ADD CONSTRAINT "cards_group_members_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_members" ADD CONSTRAINT "cards_group_members_invited_by_fkey" FOREIGN KEY ("invited_by") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_sender_fkey" FOREIGN KEY ("sender_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD CONSTRAINT "cards_groups_owner_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "cards_connections_requester_idx" ON "cards"."connections" USING btree ("requester_user_id","status","updated_at");--> statement-breakpoint
CREATE INDEX "cards_connections_recipient_idx" ON "cards"."connections" USING btree ("recipient_user_id","status","updated_at");--> statement-breakpoint
CREATE INDEX "cards_dm_messages_thread_created_idx" ON "cards"."dm_messages" USING btree ("thread_id","created_at");--> statement-breakpoint
CREATE INDEX "cards_dm_threads_updated_idx" ON "cards"."dm_threads" USING btree ("updated_at");--> statement-breakpoint
CREATE INDEX "cards_group_invitations_invitee_idx" ON "cards"."group_invitations" USING btree ("invitee_user_id","status","created_at");--> statement-breakpoint
CREATE INDEX "cards_group_invitations_group_idx" ON "cards"."group_invitations" USING btree ("group_id","status","created_at");--> statement-breakpoint
CREATE UNIQUE INDEX "cards_group_invitations_pending_key" ON "cards"."group_invitations" USING btree ("group_id","invitee_user_id") WHERE status = 'pending';--> statement-breakpoint
CREATE INDEX "cards_group_members_user_idx" ON "cards"."group_members" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "cards_group_members_group_idx" ON "cards"."group_members" USING btree ("group_id","joined_at");--> statement-breakpoint
CREATE INDEX "cards_group_messages_group_created_idx" ON "cards"."group_messages" USING btree ("group_id","created_at");--> statement-breakpoint
CREATE INDEX "cards_groups_owner_idx" ON "cards"."groups" USING btree ("owner_user_id","updated_at");--> statement-breakpoint
CREATE POLICY "service role full access on connections" ON "cards"."connections" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on dm_messages" ON "cards"."dm_messages" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on dm_threads" ON "cards"."dm_threads" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_invitations" ON "cards"."group_invitations" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_members" ON "cards"."group_members" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_messages" ON "cards"."group_messages" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on groups" ON "cards"."groups" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);
