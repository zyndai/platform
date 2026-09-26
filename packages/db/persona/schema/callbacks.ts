import { sql } from 'drizzle-orm';
import { boolean, check, index, jsonb, pgTable, text, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, jsonbDefault, publicPolicy, serviceRolePolicy, tstz } from '../../lib/shared';

// owner: persona — outbound A2A calls waiting on a peer's push callback.

const ownerIsCaller = sql`(user_id = auth.uid())`;

export const outboundCallbacks = pgTable(
  'outbound_callbacks',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    // No FK: a thread can be deleted while its callback is still in flight.
    threadId: uuid('thread_id').notNull(),
    peerAgentId: text('peer_agent_id').notNull(),
    peerTaskId: text('peer_task_id'),
    ourMessageId: text('our_message_id').notNull(),
    originKind: text('origin_kind').notNull(),
    originRef: jsonb('origin_ref').notNull().default(jsonbDefault('{}')),
    pushToken: text('push_token').notNull().unique('outbound_callbacks_push_token_key'),
    status: text('status').notNull().default('pending'),
    expiresAt: tstz('expires_at').notNull().default(sql`(now() + '24:00:00'::interval)`),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
    peerA2aUrl: text('peer_a2a_url'),
    lastState: text('last_state'),
    lastEvent: jsonb('last_event'),
    lastEventAt: tstz('last_event_at'),
    answerText: text('answer_text'),
    terminalState: text('terminal_state'),
  },
  (t) => [
    fk('outbound_callbacks_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    check('outbound_callbacks_status_check', sql`status IN ('pending', 'received', 'expired', 'failed')`),
    index('outbound_callbacks_expires_idx').on(t.expiresAt).where(sql`status = 'pending'`),
    index('outbound_callbacks_peer_task_idx')
      .on(t.peerAgentId, t.peerTaskId)
      .where(sql`peer_task_id IS NOT NULL`),
    index('outbound_callbacks_user_idx').on(t.userId, t.status, t.createdAt.desc().nullsFirst()),
    serviceRolePolicy('outbound_callbacks'),
    publicPolicy('Owner reads outbound_callbacks', { for: 'select', using: ownerIsCaller }),
  ],
);

export const callbackResults = pgTable(
  'callback_results',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    callbackId: uuid('callback_id').notNull().unique('callback_results_callback_id_key'),
    userId: uuid('user_id').notNull(),
    threadId: uuid('thread_id').notNull(),
    peerAgentId: text('peer_agent_id').notNull(),
    taskState: text('task_state').notNull(),
    replyText: text('reply_text'),
    rawEvent: jsonb('raw_event').notNull(),
    deliveredToUi: boolean('delivered_to_ui').notNull().default(false),
    createdAt: tstz('created_at').defaultNow(),
  },
  (t) => [
    fk('callback_results_callback_id_fkey', t.callbackId, outboundCallbacks.id, 'cascade'),
    fk('callback_results_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    index('callback_results_thread_idx').on(t.threadId, t.createdAt.desc().nullsFirst()),
    index('callback_results_user_idx').on(t.userId, t.deliveredToUi, t.createdAt.desc().nullsFirst()),
    serviceRolePolicy('callback_results'),
    publicPolicy('Owner reads callback_results', { for: 'select', using: ownerIsCaller }),
    publicPolicy('Owner marks delivered', { for: 'update', using: ownerIsCaller, withCheck: ownerIsCaller }),
  ],
);
