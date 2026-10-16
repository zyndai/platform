import { sql } from 'drizzle-orm';
import { bigserial, check, index, jsonb, pgPolicy, text } from 'drizzle-orm/pg-core';
import { serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';

// owner: cards. S04 analytics: no raw IP/email or conversation bodies.
// Validated profile-chat events may include a bounded, redacted question excerpt.
// Retention: DELETE WHERE ts < now() - interval '180 days' via
// POST /internal/purge-card-events. Rollback: DROP VIEW cards.v_funnel_daily;
// DROP TABLE cards.card_events;
export const cardEvents = cards.table(
  'card_events',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    ts: tstz('ts').notNull().defaultNow(),
    event: text('event').notNull(),
    handle: text('handle'),
    actorClass: text('actor_class').notNull().default('unknown'),
    ref: text('ref'),
    sessionHash: text('session_hash'),
    meta: jsonb('meta'),
  },
  (t) => [
    check(
      'card_events_actor_class_check',
      sql`actor_class IN ('human', 'ai_agent', 'search_bot', 'unknown')`,
    ),
    index('card_events_event_ts_idx').on(t.event, t.ts),
    index('card_events_handle_ts_idx').on(t.handle, t.ts),
    pgPolicy('service role full access on card_events', {
      as: 'permissive',
      for: 'all',
      to: serviceRole,
      using: sql`true`,
      withCheck: sql`true`,
    }),
  ],
);
