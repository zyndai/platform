import { sql } from 'drizzle-orm';
import { check, index, pgPolicy, primaryKey, real, text, uniqueIndex, uuid } from 'drizzle-orm/pg-core';
import { fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards — Asks (docs/plans/ZYND_ASKS_PLAN.md). A beacon becomes an ask that is routed to the
// people who can help, records who offered, closes with an outcome and leaves a credit on the helper's
// card. Written and read only by cards-api (services/asks.py); service-role only. Until these tables
// exist cards-api quietly switches the asks features off and everything else works.

// One row per posted ask. `id` is the id stored in the card's beacon JSON (made by cards-api), so the
// feed and the card can name the ask without a lookup. Active = ended_at IS NULL AND expires_at > now().
export const asks = cards.table(
  'asks',
  {
    id: uuid('id').primaryKey(),
    cardId: text('card_id').notNull(),
    ownerUserId: uuid('owner_user_id'),
    text: text('text').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
    expiresAt: tstz('expires_at').notNull(),
    endedAt: tstz('ended_at'),
    endReason: text('end_reason'),
    outcome: text('outcome'),
    outcomeAt: tstz('outcome_at'),
    outcomePromptedAt: tstz('outcome_prompted_at'),
  },
  (t) => [
    fk('asks_card_id_fkey', t.cardId, agentProfileCards.id, 'cascade'),
    check('asks_text_check', sql`char_length(text) BETWEEN 1 AND 280`),
    check('asks_end_reason_check', sql`end_reason IS NULL OR end_reason IN ('dismissed', 'replaced', 'solved')`),
    check('asks_outcome_check', sql`outcome IS NULL OR outcome IN ('helped', 'solved_elsewhere', 'still_looking')`),
    index('asks_card_created_idx').on(t.cardId, t.createdAt.desc()),
    pgPolicy('service role full access on asks', {
      as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
    }),
  ],
);

// Who offered help on an ask: written when a feed reply to the ask succeeds. credited_at is set by the
// asker's outcome (only offerers can be credited); the helper can hide the credit (credit_hidden_at);
// credit_notified_at marks the helper's digest line as sent.
export const askOffers = cards.table(
  'ask_offers',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    askId: uuid('ask_id').notNull(),
    helperUserId: uuid('helper_user_id').notNull(),
    helperCardId: text('helper_card_id').notNull(),
    connectionId: uuid('connection_id'),
    channel: text('channel').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
    creditedAt: tstz('credited_at'),
    creditHiddenAt: tstz('credit_hidden_at'),
    creditNotifiedAt: tstz('credit_notified_at'),
  },
  (t) => [
    fk('ask_offers_ask_id_fkey', t.askId, asks.id, 'cascade'),
    fk('ask_offers_helper_card_id_fkey', t.helperCardId, agentProfileCards.id, 'cascade'),
    check('ask_offers_channel_check', sql`channel IN ('dm', 'request')`),
    uniqueIndex('ask_offers_ask_helper_key').on(t.askId, t.helperUserId),
    index('ask_offers_credited_idx').on(t.helperCardId).where(sql`credited_at IS NOT NULL`),
    pgPolicy('service role full access on ask_offers', {
      as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
    }),
  ],
);

// Who an ask was routed to (the people search's best matches, minus blocks and hides): they see it in
// their feed with a boost and, once, in their morning digest (digest_sent_at).
export const askRoutes = cards.table(
  'ask_routes',
  {
    askId: uuid('ask_id').notNull(),
    helperCardId: text('helper_card_id').notNull(),
    score: real('score').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
    digestSentAt: tstz('digest_sent_at'),
  },
  (t) => [
    primaryKey({ name: 'ask_routes_pkey', columns: [t.askId, t.helperCardId] }),
    fk('ask_routes_ask_id_fkey', t.askId, asks.id, 'cascade'),
    fk('ask_routes_helper_card_id_fkey', t.helperCardId, agentProfileCards.id, 'cascade'),
    index('ask_routes_helper_idx').on(t.helperCardId, t.digestSentAt),
    pgPolicy('service role full access on ask_routes', {
      as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
    }),
  ],
);
