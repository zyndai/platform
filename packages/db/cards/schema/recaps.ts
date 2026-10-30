import { sql } from 'drizzle-orm';
import { check, date, index, jsonb, pgPolicy, text, unique, uuid } from 'drizzle-orm/pg-core';
import { fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards. Owner-confirmed milestones and private-until-published recap snapshots.
const access = (name: string) => pgPolicy(`service role full access on ${name}`, {
  as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
});

export const cardMilestones = cards.table('card_milestones', {
  id: uuid('id').primaryKey().defaultRandom(),
  cardId: text('card_id').notNull(),
  ownerEmail: text('owner_email').notNull(),
  kind: text('kind').notNull(),
  title: text('title').notNull(),
  url: text('url').notNull().default(''),
  occurredOn: date('occurred_on').notNull(),
  createdAt: tstz('created_at').notNull().defaultNow(),
}, (t) => [
  fk('card_milestones_card_id_fkey', t.cardId, agentProfileCards.id, 'cascade'),
  unique('card_milestones_dedupe').on(t.cardId, t.ownerEmail, t.kind, t.title, t.occurredOn),
  index('card_milestones_period_idx').on(t.cardId, t.occurredOn),
  check('card_milestones_kind_check', sql`${t.kind} IN ('shipped', 'learned')`),
  check('card_milestones_title_check', sql`char_length(${t.title}) BETWEEN 1 AND 140`),
  access('card_milestones'),
]);

export const cardRecaps = cards.table('card_recaps', {
  id: uuid('id').primaryKey().defaultRandom(),
  cardId: text('card_id').notNull(),
  ownerEmail: text('owner_email').notNull(),
  period: text('period').notNull(),
  snapshot: jsonb('snapshot').notNull(),
  selectedIds: jsonb('selected_ids').notNull().default(sql`'[]'::jsonb`),
  caption: text('caption').notNull().default(''),
  publishedAt: tstz('published_at'),
  createdAt: tstz('created_at').notNull().defaultNow(),
}, (t) => [
  fk('card_recaps_card_id_fkey', t.cardId, agentProfileCards.id, 'cascade'),
  unique('card_recaps_card_period').on(t.cardId, t.ownerEmail, t.period),
  index('card_recaps_owner_idx').on(t.ownerEmail, t.createdAt),
  check('card_recaps_period_check', sql`${t.period} ~ '^[0-9]{4}-(0[1-9]|1[0-2]|Q[1-4])$'`),
  check('card_recaps_caption_check', sql`char_length(${t.caption}) <= 2000`),
  access('card_recaps'),
]);
