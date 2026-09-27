import { sql } from 'drizzle-orm';
import { check, index, integer, jsonb, pgTable, text, unique, uniqueIndex, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, publicPolicy, serviceRolePolicy, tstz } from '../../lib/shared';

// owner: persona — persona groups. is_persona_group_member / _manager are
// SECURITY DEFINER functions created in migration 0000; the policies here call them.

const isMember = (column: string) => sql.raw(`is_persona_group_member(${column})`);
const svc = (table: string) => serviceRolePolicy(table, { withCheck: true, lowerCase: true });

export const personaGroups = pgTable(
  'persona_groups',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    slug: text('slug').notNull().unique('persona_groups_slug_key'),
    name: text('name').notNull(),
    description: text('description'),
    avatarUrl: text('avatar_url'),
    ownerUserId: uuid('owner_user_id').notNull(),
    visibility: text('visibility').notNull().default('private'),
    inviteToken: text('invite_token').unique('persona_groups_invite_token_key'),
    groupSeedIndex: integer('group_seed_index').notNull().default(0),
    archivedAt: tstz('archived_at'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
    briefDocId: text('brief_doc_id'),
    briefDocUrl: text('brief_doc_url'),
    joinDomain: text('join_domain'),
  },
  (t) => [
    fk('persona_groups_owner_user_id_fkey', t.ownerUserId, authUsers.id, 'cascade'),
    check('persona_groups_visibility_check', sql`visibility IN ('private', 'open')`),
    index('persona_groups_join_domain_idx')
      .on(t.joinDomain)
      .where(sql`(join_domain IS NOT NULL) AND (archived_at IS NULL)`),
    index('persona_groups_owner_idx').on(t.ownerUserId),
    svc('persona_groups'),
    publicPolicy('members read group', { for: 'select', using: isMember('id') }),
  ],
);

export const personaGroupMembers = pgTable(
  'persona_group_members',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    userId: uuid('user_id').notNull(),
    agentId: text('agent_id'),
    role: text('role').notNull().default('member'),
    permissions: jsonb('permissions')
      .notNull()
      .default(
        sql`jsonb_build_object('can_see_brief', false, 'can_see_member_briefs', false, 'can_see_group_brief', true, 'can_query_calendar', false, 'can_post', true, 'can_invite', false, 'can_speak_for_group', false)`,
      ),
    invitedBy: uuid('invited_by'),
    joinedAt: tstz('joined_at').notNull().defaultNow(),
  },
  (t) => [
    fk('persona_group_members_group_id_fkey', t.groupId, personaGroups.id, 'cascade'),
    fk('persona_group_members_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    fk('persona_group_members_invited_by_fkey', t.invitedBy, authUsers.id, 'set null'),
    unique('persona_group_members_group_id_user_id_key').on(t.groupId, t.userId),
    check('persona_group_members_role_check', sql`role IN ('owner', 'admin', 'member')`),
    index('persona_group_members_agent_idx').on(t.agentId),
    index('persona_group_members_user_idx').on(t.userId),
    svc('persona_group_members'),
    publicPolicy('members read roster', { for: 'select', using: isMember('group_id') }),
  ],
);

export const personaGroupMessages = pgTable(
  'persona_group_messages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    senderUserId: uuid('sender_user_id'),
    senderAgentId: text('sender_agent_id'),
    senderName: text('sender_name'),
    channel: text('channel').notNull().default('human'),
    content: text('content').notNull(),
    replyTo: uuid('reply_to'),
    metadata: jsonb('metadata'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('persona_group_messages_group_id_fkey', t.groupId, personaGroups.id, 'cascade'),
    fk('persona_group_messages_sender_user_id_fkey', t.senderUserId, authUsers.id, 'set null'),
    fk('persona_group_messages_reply_to_fkey', t.replyTo, t.id, 'set null'),
    check('persona_group_messages_channel_check', sql`channel IN ('human', 'agent', 'system', 'broadcast')`),
    index('persona_group_messages_group_idx').on(t.groupId, t.createdAt.desc().nullsFirst()),
    svc('persona_group_messages'),
    publicPolicy('members read messages', { for: 'select', using: isMember('group_id') }),
  ],
);

// RLS on, no policies: only the service role reads or writes invitations.
export const personaGroupInvitations = pgTable(
  'persona_group_invitations',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    inviteeUserId: uuid('invitee_user_id').notNull(),
    inviterUserId: uuid('inviter_user_id'),
    inviteeRole: text('invitee_role').notNull().default('member'),
    status: text('status').notNull().default('pending'),
    message: text('message'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    decidedAt: tstz('decided_at'),
    expiresAt: tstz('expires_at').notNull().default(sql`(now() + '7 days'::interval)`),
  },
  (t) => [
    fk('persona_group_invitations_group_id_fkey', t.groupId, personaGroups.id, 'cascade'),
    fk('persona_group_invitations_invitee_user_id_fkey', t.inviteeUserId, authUsers.id, 'cascade'),
    fk('persona_group_invitations_inviter_user_id_fkey', t.inviterUserId, authUsers.id, 'set null'),
    check('persona_group_invitations_invitee_role_check', sql`invitee_role IN ('admin', 'member')`),
    check(
      'persona_group_invitations_status_check',
      sql`status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')`,
    ),
    index('persona_group_invitations_group_status_idx').on(t.groupId, t.status),
    index('persona_group_invitations_invitee_status_idx').on(t.inviteeUserId, t.status),
    uniqueIndex('persona_group_invitations_open_uniq')
      .on(t.groupId, t.inviteeUserId)
      .where(sql`status = 'pending'`),
  ],
).enableRLS();

export const personaGroupConstraints = pgTable(
  'persona_group_constraints',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    kind: text('kind').notNull(),
    text: text('text').notNull(),
    createdByUserId: uuid('created_by_user_id'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    archivedAt: tstz('archived_at'),
  },
  (t) => [
    fk('persona_group_constraints_group_id_fkey', t.groupId, personaGroups.id, 'cascade'),
    fk('persona_group_constraints_created_by_user_id_fkey', t.createdByUserId, authUsers.id, 'set null'),
    check('persona_group_constraints_kind_check', sql`kind IN ('fact', 'rule', 'voice')`),
    check('persona_group_constraints_text_check', sql`(length(text) >= 1) AND (length(text) <= 400)`),
    index('persona_group_constraints_group_idx').on(t.groupId, t.archivedAt.asc().nullsFirst(), t.createdAt.desc().nullsFirst()),
    svc('persona_group_constraints'),
    publicPolicy('members read group constraints', { for: 'select', using: isMember('group_id') }),
  ],
);

export const personaGroupAuditEvents = pgTable(
  'persona_group_audit_events',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    affectedUserId: uuid('affected_user_id').notNull(),
    actorUserId: uuid('actor_user_id'),
    kind: text('kind').notNull(),
    metadata: jsonb('metadata'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('persona_group_audit_events_group_id_fkey', t.groupId, personaGroups.id, 'cascade'),
    fk('persona_group_audit_events_affected_user_id_fkey', t.affectedUserId, authUsers.id, 'cascade'),
    fk('persona_group_audit_events_actor_user_id_fkey', t.actorUserId, authUsers.id, 'set null'),
    check('persona_group_audit_events_kind_check', sql`kind IN ('brief_shared', 'calendar_queried')`),
    index('persona_group_audit_events_affected_idx').on(t.affectedUserId, t.createdAt.desc().nullsFirst()),
    index('persona_group_audit_events_group_idx').on(t.groupId, t.createdAt.desc().nullsFirst()),
    svc('persona_group_audit_events'),
    publicPolicy('affected user reads own audit events', {
      for: 'select',
      using: sql`(auth.uid() = affected_user_id)`,
    }),
    publicPolicy('owner reads group audit events', {
      for: 'select',
      using: sql`is_persona_group_manager(group_id)`,
    }),
  ],
);
