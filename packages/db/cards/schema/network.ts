import { sql } from 'drizzle-orm';
import { check, index, pgPolicy, pgTable, text, unique, uniqueIndex, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards — Cards-native connections, direct messages, groups, and group invitations.
// All writes go through cards-api so the API can enforce the verified-card and
// accepted-connection rules. The tables are service-role-only by design.

const serviceOnly = (table: string) => pgPolicy(`service role full access on ${table}`, {
  as: 'permissive',
  for: 'all',
  to: serviceRole,
  using: sql`true`,
  withCheck: sql`true`,
});

export const cardConnections = cards.table(
  'connections',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    connectionKey: text('connection_key').notNull(),
    requesterUserId: uuid('requester_user_id').notNull(),
    requesterCardId: text('requester_card_id').notNull(),
    recipientUserId: uuid('recipient_user_id').notNull(),
    recipientCardId: text('recipient_card_id').notNull(),
    status: text('status').notNull().default('pending'),
    requestMessage: text('request_message'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    decidedAt: tstz('decided_at'),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_connections_requester_user_fkey', t.requesterUserId, authUsers.id, 'cascade'),
    fk('cards_connections_requester_card_fkey', t.requesterCardId, agentProfileCards.id, 'cascade'),
    fk('cards_connections_recipient_user_fkey', t.recipientUserId, authUsers.id, 'cascade'),
    fk('cards_connections_recipient_card_fkey', t.recipientCardId, agentProfileCards.id, 'cascade'),
    unique('cards_connections_key_key').on(t.connectionKey),
    check('cards_connections_status_check', sql`status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked')`),
    index('cards_connections_requester_idx').on(t.requesterUserId, t.status, t.updatedAt),
    index('cards_connections_recipient_idx').on(t.recipientUserId, t.status, t.updatedAt),
    serviceOnly('connections'),
  ],
);

export const cardDmThreads = cards.table(
  'dm_threads',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    connectionId: uuid('connection_id').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_dm_threads_connection_fkey', t.connectionId, cardConnections.id, 'cascade'),
    unique('cards_dm_threads_connection_key').on(t.connectionId),
    index('cards_dm_threads_updated_idx').on(t.updatedAt),
    serviceOnly('dm_threads'),
  ],
);

export const cardDmMessages = cards.table(
  'dm_messages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    threadId: uuid('thread_id').notNull(),
    senderUserId: uuid('sender_user_id').notNull(),
    content: text('content').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_dm_messages_thread_fkey', t.threadId, cardDmThreads.id, 'cascade'),
    fk('cards_dm_messages_sender_fkey', t.senderUserId, authUsers.id, 'cascade'),
    index('cards_dm_messages_thread_created_idx').on(t.threadId, t.createdAt),
    serviceOnly('dm_messages'),
  ],
);

export const cardGroups = cards.table(
  'groups',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    name: text('name').notNull(),
    description: text('description'),
    ownerUserId: uuid('owner_user_id').notNull(),
    visibility: text('visibility').notNull().default('private'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
    archivedAt: tstz('archived_at'),
  },
  (t) => [
    fk('cards_groups_owner_fkey', t.ownerUserId, authUsers.id, 'cascade'),
    check('cards_groups_visibility_check', sql`visibility IN ('private', 'open')`),
    index('cards_groups_owner_idx').on(t.ownerUserId, t.updatedAt),
    serviceOnly('groups'),
  ],
);

export const cardGroupMembers = cards.table(
  'group_members',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    userId: uuid('user_id').notNull(),
    role: text('role').notNull().default('member'),
    invitedBy: uuid('invited_by'),
    joinedAt: tstz('joined_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_members_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_members_user_fkey', t.userId, authUsers.id, 'cascade'),
    fk('cards_group_members_invited_by_fkey', t.invitedBy, authUsers.id, 'set null'),
    unique('cards_group_members_group_user_key').on(t.groupId, t.userId),
    check('cards_group_members_role_check', sql`role IN ('owner', 'member')`),
    index('cards_group_members_user_idx').on(t.userId),
    index('cards_group_members_group_idx').on(t.groupId, t.joinedAt),
    serviceOnly('group_members'),
  ],
);

export const cardGroupInvitations = cards.table(
  'group_invitations',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    inviteeUserId: uuid('invitee_user_id').notNull(),
    inviterUserId: uuid('inviter_user_id').notNull(),
    status: text('status').notNull().default('pending'),
    message: text('message'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    decidedAt: tstz('decided_at'),
    expiresAt: tstz('expires_at').notNull().default(sql`(now() + '7 days'::interval)`),
  },
  (t) => [
    fk('cards_group_invitations_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_invitations_invitee_fkey', t.inviteeUserId, authUsers.id, 'cascade'),
    fk('cards_group_invitations_inviter_fkey', t.inviterUserId, authUsers.id, 'cascade'),
    check('cards_group_invitations_status_check', sql`status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')`),
    index('cards_group_invitations_invitee_idx').on(t.inviteeUserId, t.status, t.createdAt),
    index('cards_group_invitations_group_idx').on(t.groupId, t.status, t.createdAt),
    uniqueIndex('cards_group_invitations_pending_key')
      .on(t.groupId, t.inviteeUserId)
      .where(sql`status = 'pending'`),
    serviceOnly('group_invitations'),
  ],
);

export const cardGroupMessages = cards.table(
  'group_messages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    senderUserId: uuid('sender_user_id').notNull(),
    content: text('content').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_messages_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_messages_sender_fkey', t.senderUserId, authUsers.id, 'cascade'),
    index('cards_group_messages_group_created_idx').on(t.groupId, t.createdAt),
    serviceOnly('group_messages'),
  ],
);
