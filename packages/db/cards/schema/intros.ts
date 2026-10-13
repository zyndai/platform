import { sql } from 'drizzle-orm';
import { index, pgPolicy, text, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards. Minimal projection, no request text/contact information.
export const introRequests = cards.table('intro_requests', {
  id: uuid('id').primaryKey(),
  cardId: text('card_id').notNull(),
  handle: text('handle').notNull(),
  ownerUid: uuid('owner_uid').notNull(),
  requesterUid: uuid('requester_uid').notNull(),
  status: text('status').notNull(),
  createdAt: tstz('created_at').notNull(),
  acceptedAt: tstz('accepted_at'),
}, t => [
  fk('cards_intro_card_fkey', t.cardId, agentProfileCards.id, 'cascade'),
  fk('cards_intro_owner_fkey', t.ownerUid, authUsers.id, 'cascade'),
  fk('cards_intro_requester_fkey', t.requesterUid, authUsers.id, 'cascade'),
  index('cards_intro_owner_created_idx').on(t.ownerUid, t.createdAt),
  pgPolicy('service role full access on intro_requests', {for:'all', to:serviceRole, using:sql`true`, withCheck:sql`true`}),
]);
