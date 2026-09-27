import { sql } from 'drizzle-orm';
import { index, jsonb, pgPolicy, text, uuid } from 'drizzle-orm/pg-core';
import { fk, jsonbDefault, serviceRole, tstz } from '../../lib/shared';
import { agentProfileCards } from './cards';
import { cards } from './_schema';

// owner: cards — the @zynd X (Twitter) bot's state. Moved from xmfj as-is.
// Service role only, like xmfj.

const serviceOnly = (table: string) =>
  pgPolicy(`service role full access on ${table}`, {
    as: 'permissive',
    for: 'all',
    to: serviceRole,
    using: sql`true`,
    withCheck: sql`true`,
  });

export const xAccounts = cards.table(
  'x_accounts',
  {
    xUserId: text('x_user_id').primaryKey(),
    username: text('username').notNull(),
    cardId: text('card_id'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [fk('x_accounts_card_id_fkey', t.cardId, agentProfileCards.id), serviceOnly('x_accounts')],
);

export const xConversations = cards.table(
  'x_conversations',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    xUserId: text('x_user_id').notNull(),
    cardId: text('card_id'),
    status: text('status').notNull().default('initial'),
    currentQuestion: text('current_question'),
    answered: jsonb('answered').notNull().default(jsonbDefault('{}')),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    fk('x_conversations_card_id_fkey', t.cardId, agentProfileCards.id),
    index('x_conversations_user_idx').on(t.xUserId),
    serviceOnly('x_conversations'),
  ],
);

export const xMentions = cards.table(
  'x_mentions',
  {
    tweetId: text('tweet_id').primaryKey(),
    xUserId: text('x_user_id').notNull(),
    text: text('text'),
    status: text('status').notNull().default('processed'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [index('x_mentions_user_idx').on(t.xUserId), serviceOnly('x_mentions')],
);
