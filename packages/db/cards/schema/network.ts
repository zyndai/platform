import { sql } from 'drizzle-orm';
import {
  bigint,
  boolean,
  check,
  index,
  integer,
  jsonb,
  pgPolicy,
  pgTable,
  primaryKey,
  text,
  unique,
  uniqueIndex,
  uuid,
  vector,
} from 'drizzle-orm/pg-core';
import { authUsers, fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards — Cards-native connections, direct messages, groups, and group invitations.
// All writes go through cards-api so the API can enforce the verified-card and
// accepted-connection rules. The tables are service-role-only by design.
//
// Messaging v2 adds a per-conversation sequence (`seq`), idempotent sends
// (`client_id`), inbox summaries, and per-user read cursors. The sequence is
// assigned by a database trigger under the parent row lock, so it is stable,
// gap-free per conversation, and safe to use as a pagination cursor.

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
    messageCount: bigint('message_count', { mode: 'number' }).notNull().default(0),
    lastMessageAt: tstz('last_message_at'),
    lastMessagePreview: text('last_message_preview'),
    lastMessageSenderUserId: uuid('last_message_sender_user_id'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_dm_threads_connection_fkey', t.connectionId, cardConnections.id, 'cascade'),
    fk('cards_dm_threads_last_sender_fkey', t.lastMessageSenderUserId, authUsers.id, 'set null'),
    unique('cards_dm_threads_connection_key').on(t.connectionId),
    check('cards_dm_threads_message_count_check', sql`message_count >= 0`),
    index('cards_dm_threads_updated_idx').on(t.updatedAt),
    index('cards_dm_threads_last_message_idx').on(t.lastMessageAt.desc().nullsLast()),
    serviceOnly('dm_threads'),
  ],
);

export const cardDmMessages = cards.table(
  'dm_messages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    threadId: uuid('thread_id').notNull(),
    seq: bigint('seq', { mode: 'number' }).notNull(),
    clientId: uuid('client_id'),
    senderUserId: uuid('sender_user_id').notNull(),
    content: text('content').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_dm_messages_thread_fkey', t.threadId, cardDmThreads.id, 'cascade'),
    fk('cards_dm_messages_sender_fkey', t.senderUserId, authUsers.id, 'cascade'),
    check('cards_dm_messages_seq_check', sql`seq > 0`),
    uniqueIndex('cards_dm_messages_thread_seq_key').on(t.threadId, t.seq),
    uniqueIndex('cards_dm_messages_client_key')
      .on(t.threadId, t.senderUserId, t.clientId)
      .where(sql`client_id IS NOT NULL`),
    index('cards_dm_messages_thread_created_idx').on(t.threadId, t.createdAt),
    serviceOnly('dm_messages'),
  ],
);

export const cardDmReadState = cards.table(
  'dm_read_state',
  {
    threadId: uuid('thread_id').notNull(),
    userId: uuid('user_id').notNull(),
    lastReadSeq: bigint('last_read_seq', { mode: 'number' }).notNull().default(0),
    lastReadAt: tstz('last_read_at').notNull().defaultNow(),
  },
  (t) => [
    primaryKey({ name: 'cards_dm_read_state_pkey', columns: [t.threadId, t.userId] }),
    fk('cards_dm_read_state_thread_fkey', t.threadId, cardDmThreads.id, 'cascade'),
    fk('cards_dm_read_state_user_fkey', t.userId, authUsers.id, 'cascade'),
    check('cards_dm_read_state_seq_check', sql`last_read_seq >= 0`),
    index('cards_dm_read_state_user_idx').on(t.userId, t.lastReadAt.desc()),
    serviceOnly('dm_read_state'),
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
    messageCount: bigint('message_count', { mode: 'number' }).notNull().default(0),
    lastMessageAt: tstz('last_message_at'),
    lastMessagePreview: text('last_message_preview'),
    lastMessageSenderUserId: uuid('last_message_sender_user_id'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
    archivedAt: tstz('archived_at'),
  },
  (t) => [
    fk('cards_groups_owner_fkey', t.ownerUserId, authUsers.id, 'cascade'),
    fk('cards_groups_last_sender_fkey', t.lastMessageSenderUserId, authUsers.id, 'set null'),
    check('cards_groups_visibility_check', sql`visibility IN ('private', 'open')`),
    check('cards_groups_message_count_check', sql`message_count >= 0`),
    index('cards_groups_owner_idx').on(t.ownerUserId, t.updatedAt),
    index('cards_groups_last_message_idx').on(t.lastMessageAt.desc().nullsLast()),
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
    seq: bigint('seq', { mode: 'number' }).notNull(),
    clientId: uuid('client_id'),
    senderUserId: uuid('sender_user_id').notNull(),
    // "user" messages are written by the member. "agent" messages are written
    // by the Card AI assistant on behalf of agent_for_user_id and are always
    // labelled as AI in the UI. Agent messages never trigger more agents.
    senderKind: text('sender_kind').notNull().default('user'),
    agentForUserId: uuid('agent_for_user_id'),
    replyToMessageId: uuid('reply_to_message_id'),
    mentions: uuid('mentions').array().notNull().default(sql`'{}'::uuid[]`),
    content: text('content').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_messages_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_messages_sender_fkey', t.senderUserId, authUsers.id, 'cascade'),
    fk('cards_group_messages_agent_for_user_id_fkey', t.agentForUserId, authUsers.id, 'set null'),
    fk('cards_group_messages_reply_to_message_id_fkey', t.replyToMessageId, t.id, 'set null'),
    check('cards_group_messages_sender_kind_check', sql`sender_kind IN ('user', 'agent')`),
    check('cards_group_messages_agent_identity_check', sql`sender_kind = 'user' OR agent_for_user_id IS NOT NULL`),
    check('cards_group_messages_seq_check', sql`seq > 0`),
    uniqueIndex('cards_group_messages_group_seq_key').on(t.groupId, t.seq),
    uniqueIndex('cards_group_messages_client_key')
      .on(t.groupId, t.senderUserId, t.clientId)
      .where(sql`client_id IS NOT NULL`),
    index('cards_group_messages_group_created_idx').on(t.groupId, t.createdAt),
    serviceOnly('group_messages'),
  ],
);

export const cardGroupReadState = cards.table(
  'group_read_state',
  {
    groupId: uuid('group_id').notNull(),
    userId: uuid('user_id').notNull(),
    lastReadSeq: bigint('last_read_seq', { mode: 'number' }).notNull().default(0),
    lastReadAt: tstz('last_read_at').notNull().defaultNow(),
  },
  (t) => [
    primaryKey({ name: 'cards_group_read_state_pkey', columns: [t.groupId, t.userId] }),
    fk('cards_group_read_state_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_read_state_user_fkey', t.userId, authUsers.id, 'cascade'),
    check('cards_group_read_state_seq_check', sql`last_read_seq >= 0`),
    index('cards_group_read_state_user_idx').on(t.userId, t.lastReadAt.desc()),
    serviceOnly('group_read_state'),
  ],
);

// owner: cards — durable group memory. The conversation itself is not copied
// here: agents receive the last N messages as raw context, while this table
// holds the rolling summary and the small set of durable facts worth keeping.
// `source_message_id` is set for a fact a member explicitly remembered; the
// link table below is what the UI uses to paint that message in the accent
// colour.
export const cardGroupMemory = cards.table(
  'group_memory',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    kind: text('kind').notNull(),
    content: text('content').notNull(),
    contentHash: text('content_hash').notNull(),
    sourceMessageId: uuid('source_message_id'),
    createdBy: uuid('created_by'),
    metadata: jsonb('metadata').notNull().default(sql`'{}'::jsonb`),
    embedding: vector('embedding', { dimensions: 1536 }),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_memory_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_memory_source_message_fkey', t.sourceMessageId, cardGroupMessages.id, 'set null'),
    fk('cards_group_memory_created_by_fkey', t.createdBy, authUsers.id, 'set null'),
    check('cards_group_memory_kind_check', sql`kind IN ('summary', 'fact')`),
    check('cards_group_memory_content_check', sql`char_length(content) BETWEEN 1 AND 4000`),
    uniqueIndex('cards_group_memory_summary_key')
      .on(t.groupId)
      .where(sql`kind = 'summary'`),
    uniqueIndex('cards_group_memory_fact_hash_key')
      .on(t.groupId, t.contentHash)
      .where(sql`kind = 'fact'`),
    index('cards_group_memory_group_created_idx').on(t.groupId, t.createdAt.desc()),
    index('cards_group_memory_embedding_hnsw_idx').using('hnsw', t.embedding.op('vector_cosine_ops')),
    serviceOnly('group_memory'),
  ],
);

// owner: cards — one row per group tracking how far the rolling summary has
// read. Keeping the cursor here means a failed summary job retries from the
// same place instead of skipping messages.
export const cardGroupMemoryState = cards.table(
  'group_memory_state',
  {
    groupId: uuid('group_id').primaryKey(),
    lastSummarizedSeq: bigint('last_summarized_seq', { mode: 'number' }).notNull().default(0),
    summaryMemoryId: uuid('summary_memory_id'),
    summaryUpdatedAt: tstz('summary_updated_at'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_memory_state_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_memory_state_summary_fkey', t.summaryMemoryId, cardGroupMemory.id, 'set null'),
    check('cards_group_memory_state_seq_check', sql`last_summarized_seq >= 0`),
    serviceOnly('group_memory_state'),
  ],
);

// owner: cards — the message a member chose to remember. One message maps to
// one fact; the fact may also be reused by the summarizer.
export const cardGroupMessageMemory = cards.table(
  'group_message_memory',
  {
    messageId: uuid('message_id').primaryKey(),
    memoryId: uuid('memory_id').notNull(),
    createdBy: uuid('created_by'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_message_memory_message_fkey', t.messageId, cardGroupMessages.id, 'cascade'),
    fk('cards_group_message_memory_memory_fkey', t.memoryId, cardGroupMemory.id, 'cascade'),
    fk('cards_group_message_memory_created_by_fkey', t.createdBy, authUsers.id, 'set null'),
    index('cards_group_message_memory_memory_idx').on(t.memoryId),
    serviceOnly('group_message_memory'),
  ],
);

// owner: cards — a durable queue for Card AI assistant replies. Sending a
// message stays fast; the worker claims one job at a time with SKIP LOCKED.
export const cardGroupAgentJobs = cards.table(
  'group_agent_jobs',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    groupId: uuid('group_id').notNull(),
    messageId: uuid('message_id').notNull(),
    mentionedUserId: uuid('mentioned_user_id').notNull(),
    status: text('status').notNull().default('pending'),
    attempts: integer('attempts').notNull().default(0),
    availableAt: tstz('available_at').notNull().defaultNow(),
    lockedAt: tstz('locked_at'),
    lastError: text('last_error'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_agent_jobs_group_fkey', t.groupId, cardGroups.id, 'cascade'),
    fk('cards_group_agent_jobs_message_fkey', t.messageId, cardGroupMessages.id, 'cascade'),
    fk('cards_group_agent_jobs_user_fkey', t.mentionedUserId, authUsers.id, 'cascade'),
    check('cards_group_agent_jobs_status_check', sql`status IN ('pending', 'running', 'done', 'failed')`),
    uniqueIndex('cards_group_agent_jobs_message_user_key').on(t.messageId, t.mentionedUserId),
    index('cards_group_agent_jobs_ready_idx').on(t.status, t.availableAt),
    index('cards_group_agent_jobs_group_idx').on(t.groupId, t.createdAt.desc()),
    serviceOnly('group_agent_jobs'),
  ],
);

// owner: cards — per-user opt-out for automatic Card AI replies in groups.
// Missing row means enabled, so existing members get the feature without a
// backfill; the API writes a row only when someone turns it off or on.
export const cardGroupAgentPreferences = cards.table(
  'group_agent_preferences',
  {
    userId: uuid('user_id').primaryKey(),
    enabled: boolean('enabled').notNull().default(true),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_group_agent_preferences_user_fkey', t.userId, authUsers.id, 'cascade'),
    serviceOnly('group_agent_preferences'),
  ],
);

// owner: cards — an invitation from a Card owner to someone who has no claimed Card yet
// (A2, "invite to claim"). The target is a pre-filled UNCLAIMED card; when its real owner
// claims it, each pending invite is delivered as an ordinary connection request. Writes go
// through cards-api only (service role), like the rest of the network.
export const cardConnectionInvites = cards.table(
  'connection_invites',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    inviterUserId: uuid('inviter_user_id').notNull(),
    inviterCardId: text('inviter_card_id').notNull(),
    targetCardId: text('target_card_id').notNull(),
    message: text('message'),
    status: text('status').notNull().default('pending'),
    connectionId: uuid('connection_id'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    deliveredAt: tstz('delivered_at'),
    expiresAt: tstz('expires_at').notNull().default(sql`(now() + '60 days'::interval)`),
  },
  (t) => [
    fk('cards_connection_invites_inviter_user_fkey', t.inviterUserId, authUsers.id, 'cascade'),
    fk('cards_connection_invites_inviter_card_fkey', t.inviterCardId, agentProfileCards.id, 'cascade'),
    fk('cards_connection_invites_target_card_fkey', t.targetCardId, agentProfileCards.id, 'cascade'),
    fk('cards_connection_invites_connection_fkey', t.connectionId, cardConnections.id, 'set null'),
    check('cards_connection_invites_status_check', sql`status IN ('pending', 'delivered', 'cancelled', 'expired')`),
    index('cards_connection_invites_target_idx').on(t.targetCardId, t.status),
    index('cards_connection_invites_inviter_idx').on(t.inviterUserId, t.createdAt),
    uniqueIndex('cards_connection_invites_pending_key')
      .on(t.inviterUserId, t.targetCardId)
      .where(sql`status = 'pending'`),
    serviceOnly('connection_invites'),
  ],
);

// owner: cards — saved people searches (A3). A cron in cards-api re-runs each active search and
// turns new strong matches into owner nudges. `search_key` is a hash of the normalized filters so
// the same search cannot be saved twice; `seen_handles` is what has already been reported.
export const cardSavedSearches = cards.table(
  'saved_searches',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    searchKey: text('search_key').notNull(),
    label: text('label').notNull().default(''),
    q: text('q').notNull().default(''),
    role: text('role').notNull().default(''),
    location: text('location').notNull().default(''),
    skills: text('skills').notNull().default(''),
    active: boolean('active').notNull().default(true),
    seenHandles: text('seen_handles').array().notNull().default(sql`'{}'::text[]`),
    createdAt: tstz('created_at').notNull().defaultNow(),
    lastCheckedAt: tstz('last_checked_at'),
    lastNotifiedAt: tstz('last_notified_at'),
  },
  (t) => [
    fk('cards_saved_searches_user_fkey', t.userId, authUsers.id, 'cascade'),
    unique('cards_saved_searches_user_key').on(t.userId, t.searchKey),
    index('cards_saved_searches_active_idx').on(t.active, t.lastCheckedAt),
    serviceOnly('saved_searches'),
  ],
);

// owner: cards — reports of a Card for spam, impersonation or harassment (A6). Written by
// cards-api; reviewed by a person (no automated action is taken on a report).
export const cardReports = cards.table(
  'card_reports',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    reporterUserId: uuid('reporter_user_id').notNull(),
    targetCardId: text('target_card_id').notNull(),
    reason: text('reason').notNull(),
    details: text('details'),
    status: text('status').notNull().default('open'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_card_reports_reporter_fkey', t.reporterUserId, authUsers.id, 'cascade'),
    fk('cards_card_reports_target_fkey', t.targetCardId, agentProfileCards.id, 'cascade'),
    check('cards_card_reports_reason_check', sql`reason IN ('spam', 'impersonation', 'harassment', 'inaccurate', 'other')`),
    check('cards_card_reports_status_check', sql`status IN ('open', 'reviewed', 'dismissed')`),
    uniqueIndex('cards_card_reports_open_key').on(t.reporterUserId, t.targetCardId).where(sql`status = 'open'`),
    index('cards_card_reports_target_idx').on(t.targetCardId, t.status),
    serviceOnly('card_reports'),
  ],
);

// owner: cards — match controls (A8): hide a person, mute a topic, "less like this".
export const cardMatchPreferences = cards.table(
  'match_preferences',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    kind: text('kind').notNull(),
    value: text('value').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_match_preferences_user_fkey', t.userId, authUsers.id, 'cascade'),
    check('cards_match_preferences_kind_check', sql`kind IN ('hide_person', 'mute_topic', 'less_like_this')`),
    unique('cards_match_preferences_key').on(t.userId, t.kind, t.value),
    index('cards_match_preferences_user_idx').on(t.userId),
    serviceOnly('match_preferences'),
  ],
);

// owner: cards — which identities of a Card's owner have been verified (A6). Written only by
// cards-api when it has proof (today: the owner signed in with the LinkedIn account that
// matches the Card's LinkedIn profile); never part of the owner-editable card JSON, so an owner
// cannot award themselves a badge.
export const cardVerifications = cards.table(
  'card_verifications',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    cardId: text('card_id').notNull(),
    provider: text('provider').notNull(),
    verifiedAt: tstz('verified_at').notNull().defaultNow(),
  },
  (t) => [
    fk('cards_card_verifications_card_fkey', t.cardId, agentProfileCards.id, 'cascade'),
    check('cards_card_verifications_provider_check', sql`provider IN ('linkedin', 'github', 'work_email')`),
    unique('cards_card_verifications_key').on(t.cardId, t.provider),
    serviceOnly('card_verifications'),
  ],
);
