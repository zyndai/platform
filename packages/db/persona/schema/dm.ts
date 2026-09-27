import { sql } from 'drizzle-orm';
import { bigint, check, index, jsonb, pgTable, text, unique, uniqueIndex, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, isOwner, jsonbDefault, publicPolicy, serviceRolePolicy, tstz } from '../../lib/shared';

// owner: persona — DMs between personas, A2A tasks, meeting tasks, approvals.

/** The caller is a party to the thread, as a human (auth uid) or through their persona agent. */
const isThreadParty = (thread: string) =>
  sql.raw(
    `((auth.uid())::text = ${thread}.initiator_id) OR ((auth.uid())::text = ${thread}.receiver_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND ((persona_agents.agent_id = ${thread}.initiator_id) OR (persona_agents.agent_id = ${thread}.receiver_id)))))`,
  );

export const dmThreads = pgTable(
  'dm_threads',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    initiatorId: text('initiator_id').notNull(),
    receiverId: text('receiver_id').notNull(),
    initiatorName: text('initiator_name').default(''),
    receiverName: text('receiver_name').default(''),
    status: text('status').notNull().default('pending'),
    lifecycle: text('lifecycle').notNull().default('pending'),
    initiatorMode: text('initiator_mode').notNull().default('agent'),
    receiverMode: text('receiver_mode').notNull().default('agent'),
    permissions: jsonb('permissions')
      .notNull()
      .default(
        sql`jsonb_build_object('can_request_meetings', true, 'can_query_availability', false, 'can_view_full_profile', false, 'can_post_on_my_behalf', false)`,
      ),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    unique('dm_threads_initiator_id_receiver_id_key').on(t.initiatorId, t.receiverId),
    check('dm_threads_status_check', sql`status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked')`),
    check('dm_threads_initiator_mode_check', sql`initiator_mode IN ('human', 'agent')`),
    check('dm_threads_receiver_mode_check', sql`receiver_mode IN ('human', 'agent')`),
    index('dm_threads_lifecycle_idx').on(t.lifecycle),
    serviceRolePolicy('dm_threads'),
    publicPolicy('Users can read own threads', { for: 'select', using: isThreadParty('dm_threads') }),
    publicPolicy('Participants can update threads', { for: 'update', using: isThreadParty('dm_threads') }),
    publicPolicy('Users can start threads', {
      for: 'insert',
      withCheck: sql`((auth.uid())::text = initiator_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND (persona_agents.agent_id = dm_threads.initiator_id))))`,
    }),
  ],
);

/** EXISTS over the parent thread: caller is a party and the status is not in `blockedStatuses`. */
const inOpenThread = (fkExpr: string, blockedStatuses: string[]) =>
  sql.raw(`EXISTS ( SELECT 1
   FROM dm_threads t
  WHERE ((t.id = ${fkExpr}) AND ((t.initiator_id = (auth.uid())::text) OR (t.receiver_id = (auth.uid())::text) OR (EXISTS ( SELECT 1
           FROM persona_agents p
          WHERE ((p.user_id = auth.uid()) AND ((p.agent_id = t.initiator_id) OR (p.agent_id = t.receiver_id)))))) AND (t.status <> ALL (ARRAY[${blockedStatuses
    .map((s) => `'${s}'::text`)
    .join(', ')}]))))`);

export const dmMessages = pgTable(
  'dm_messages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    threadId: uuid('thread_id').notNull(),
    senderId: text('sender_id').notNull(),
    senderType: text('sender_type').notNull().default('human'),
    channel: text('channel').notNull().default('human'),
    content: text('content').notNull(),
    createdAt: tstz('created_at').defaultNow(),
  },
  (t) => [
    fk('dm_messages_thread_id_fkey', t.threadId, dmThreads.id, 'cascade'),
    check('dm_messages_sender_type_check', sql`sender_type IN ('human', 'agent', 'system')`),
    check('dm_messages_channel_check', sql`channel IN ('human', 'agent')`),
    serviceRolePolicy('dm_messages'),
    publicPolicy('Users can read messages in non-blocked threads', {
      for: 'select',
      using: inOpenThread('dm_messages.thread_id', ['blocked', 'revoked']),
    }),
    publicPolicy('Users can send messages in accepted threads', {
      for: 'insert',
      withCheck: sql`(((auth.uid())::text = sender_id) OR (EXISTS ( SELECT 1
   FROM persona_agents
  WHERE ((persona_agents.user_id = auth.uid()) AND (persona_agents.agent_id = dm_messages.sender_id))))) AND (${inOpenThread(
    'dm_messages.thread_id',
    ['blocked', 'declined', 'revoked'],
  )})`,
    }),
  ],
);

export const a2aTasks = pgTable(
  'a2a_tasks',
  {
    taskId: uuid('task_id').primaryKey(),
    contextId: uuid('context_id').notNull(),
    state: text('state').notNull().default('submitted'),
    permissionSnapshot: jsonb('permission_snapshot').notNull().default(jsonbDefault('{}')),
    history: jsonb('history').notNull().default(jsonbDefault('[]')),
    artifacts: jsonb('artifacts').notNull().default(jsonbDefault('[]')),
    pushUrl: text('push_url'),
    pushToken: text('push_token'),
    lastMessageId: text('last_message_id'),
    idleTtlMs: bigint('idle_ttl_ms', { mode: 'number' }).notNull().default(3600000),
    idleUntil: tstz('idle_until'),
    terminalAt: tstz('terminal_at'),
    failureReason: text('failure_reason'),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('a2a_tasks_context_id_fkey', t.contextId, dmThreads.id, 'cascade'),
    check(
      'a2a_tasks_state_check',
      sql`state IN ('submitted', 'working', 'input-required', 'auth-required', 'completed', 'canceled', 'failed', 'rejected')`,
    ),
    index('a2a_tasks_context_idx').on(t.contextId, t.updatedAt.desc().nullsFirst()),
    index('a2a_tasks_state_idle_idx')
      .on(t.state, t.idleUntil)
      .where(sql`state IN ('input-required', 'auth-required')`),
    serviceRolePolicy('a2a_tasks'),
    publicPolicy('Participants can read a2a_tasks', {
      for: 'select',
      using: sql`EXISTS ( SELECT 1
   FROM dm_threads t
  WHERE ((t.id = a2a_tasks.context_id) AND ((t.initiator_id = (auth.uid())::text) OR (t.receiver_id = (auth.uid())::text) OR (EXISTS ( SELECT 1
           FROM persona_agents p
          WHERE ((p.user_id = auth.uid()) AND ((p.agent_id = t.initiator_id) OR (p.agent_id = t.receiver_id))))))))`,
    }),
  ],
);

const isTaskParty = sql`(auth.uid() = initiator_user_id) OR (auth.uid() = recipient_user_id)`;

export const agentTasks = pgTable(
  'agent_tasks',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    threadId: uuid('thread_id').notNull(),
    type: text('type').notNull().default('meeting'),
    status: text('status').notNull().default('proposed'),
    initiatorUserId: uuid('initiator_user_id').notNull(),
    recipientUserId: uuid('recipient_user_id').notNull(),
    initiatorAgentId: text('initiator_agent_id').notNull(),
    recipientAgentId: text('recipient_agent_id').notNull(),
    payload: jsonb('payload').notNull().default(jsonbDefault('{}')),
    history: jsonb('history').notNull().default(jsonbDefault('[]')),
    calendarEventIds: jsonb('calendar_event_ids').notNull().default(jsonbDefault('{}')),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('agent_tasks_thread_id_fkey', t.threadId, dmThreads.id, 'cascade'),
    fk('agent_tasks_initiator_user_id_fkey', t.initiatorUserId, authUsers.id, 'cascade'),
    fk('agent_tasks_recipient_user_id_fkey', t.recipientUserId, authUsers.id, 'cascade'),
    check('agent_tasks_type_check', sql`type = 'meeting'`),
    check(
      'agent_tasks_status_check',
      sql`status IN ('proposed', 'countered', 'accepted', 'scheduled', 'declined', 'cancelled', 'book_failed')`,
    ),
    index('agent_tasks_initiator_idx').on(t.initiatorUserId),
    index('agent_tasks_recipient_idx').on(t.recipientUserId),
    index('agent_tasks_status_idx').on(t.status),
    index('agent_tasks_thread_idx').on(t.threadId),
    uniqueIndex('agent_tasks_one_open_proposal')
      .on(t.threadId)
      .where(sql`status IN ('proposed', 'countered', 'accepted')`),
    serviceRolePolicy('agent_tasks'),
    publicPolicy('Participants can read agent_tasks', { for: 'select', using: isTaskParty }),
    publicPolicy('Participants can update agent_tasks', { for: 'update', using: isTaskParty }),
  ],
);

export const pendingApprovals = pgTable(
  'pending_approvals',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    threadId: uuid('thread_id'),
    toolName: text('tool_name').notNull(),
    toolArgs: jsonb('tool_args').notNull().default(jsonbDefault('{}')),
    summary: text('summary'),
    status: text('status').notNull().default('pending'),
    result: jsonb('result'),
    createdAt: tstz('created_at').defaultNow(),
    decidedAt: tstz('decided_at'),
    expiresAt: tstz('expires_at').default(sql`(now() + '24:00:00'::interval)`),
  },
  (t) => [
    fk('pending_approvals_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    fk('pending_approvals_thread_id_fkey', t.threadId, dmThreads.id, 'cascade'),
    check('pending_approvals_status_check', sql`status IN ('pending', 'approved', 'declined', 'expired')`),
    index('pending_approvals_thread_idx').on(t.threadId),
    index('pending_approvals_user_status_idx').on(t.userId, t.status),
    serviceRolePolicy('pending_approvals'),
    publicPolicy('Users read own approvals', { for: 'select', using: isOwner('user_id') }),
    publicPolicy('Users update own approvals', { for: 'update', using: isOwner('user_id') }),
  ],
);
