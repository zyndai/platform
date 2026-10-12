import { sql } from 'drizzle-orm';
import { index, jsonb, pgPolicy, text, unique, uuid } from 'drizzle-orm/pg-core';
import { serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';

const access = (name: string) => pgPolicy(`service role full access on ${name}`, {
  as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
});

export const cardNudges = cards.table('card_nudges', {
  id: uuid('id').primaryKey().defaultRandom(),
  ownerEmail: text('owner_email').notNull(),
  handle: text('handle').notNull(),
  dedupeKey: text('dedupe_key').notNull(),
  kind: text('kind').notNull(),
  title: text('title').notNull(),
  href: text('href').notNull(),
  createdAt: tstz('created_at').notNull().defaultNow(),
  dismissedAt: tstz('dismissed_at'),
}, (t) => [unique('card_nudges_owner_key').on(t.ownerEmail, t.dedupeKey),
  index('card_nudges_owner_created_idx').on(t.ownerEmail, t.createdAt), access('card_nudges')]);

// Claim BEFORE handing a message to SMTP. Ambiguous failures require review,
// never an automatic retry that might deliver the same message twice.
export const notificationDeliveries = cards.table('notification_deliveries', {
  id: uuid('id').primaryKey().defaultRandom(),
  ownerEmail: text('owner_email').notNull(),
  kind: text('kind').notNull(),
  period: text('period').notNull(),
  status: text('status').notNull().default('claimed'),
  createdAt: tstz('created_at').notNull().defaultNow(),
  sentAt: tstz('sent_at'),
}, (t) => [unique('notification_deliveries_owner_period').on(t.ownerEmail, t.kind, t.period), access('notification_deliveries')]);

export const cardMerges = cards.table('card_merges', {
  id: uuid('id').primaryKey().defaultRandom(),
  ownerEmail: text('owner_email').notNull(),
  canonicalId: text('canonical_id').notNull(),
  archivedId: text('archived_id').notNull().unique('card_merges_archived_id_key'),
  snapshot: jsonb('snapshot').notNull(),
  createdAt: tstz('created_at').notNull().defaultNow(),
}, (t) => [index('card_merges_canonical_idx').on(t.canonicalId), access('card_merges')]);
