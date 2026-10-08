import { sql } from 'drizzle-orm';
import { index, pgPolicy, text, uuid } from 'drizzle-orm/pg-core';
import { serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';

// owner: cards. S03 "Not me" takedown queue: a visitor (or the real person)
// reports that a scraped card isn't theirs. The card row itself is moved out
// of `published` status immediately; this table is the review queue.
// Rollback: DROP TABLE IF EXISTS cards.takedown_requests;
export const takedownRequests = cards.table(
  'takedown_requests',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    handle: text('handle').notNull(),
    // The signed-in reporter's aafo user id, when they were signed in.
    requesterUserId: uuid('requester_user_id'),
    note: text('note'),
    // pending → dismissed (card restored) | actioned (card deleted).
    status: text('status').notNull().default('pending'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    index('takedown_requests_handle_idx').on(t.handle),
    index('takedown_requests_status_idx').on(t.status),
    pgPolicy('service role full access on takedown_requests', {
      as: 'permissive',
      for: 'all',
      to: serviceRole,
      using: sql`true`,
      withCheck: sql`true`,
    }),
  ],
);