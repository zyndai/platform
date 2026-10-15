import { sql } from 'drizzle-orm';
import { boolean, index, pgPolicy, text, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards. Anonymous by default. Names are read only while the same consent is active.
export const visitorPreferences = cards.table('visitor_preferences', {
  userId: uuid('user_id').primaryKey(),
  anonymousMode: boolean('anonymous_mode').notNull().default(true),
  displayName: text('display_name'),
  consentVersion: uuid('consent_version').notNull().defaultRandom(),
  updatedAt: tstz('updated_at').notNull().defaultNow(),
}, t => [
  fk('visitor_preferences_user_fkey', t.userId, authUsers.id, 'cascade'),
  pgPolicy('service role full access on visitor_preferences', {for:'all', to:serviceRole, using:sql`true`, withCheck:sql`true`}),
]);

export const profileVisits = cards.table('profile_visits', {
  id: uuid('id').primaryKey(),
  cardId: text('card_id').notNull(),
  ownerEmail: text('owner_email').notNull(),
  visitorId: uuid('visitor_id').notNull(),
  consentVersion: uuid('consent_version').notNull(),
  visitedAt: tstz('visited_at').notNull().defaultNow(),
}, t => [
  fk('profile_visits_card_fkey', t.cardId, agentProfileCards.id, 'cascade'),
  fk('profile_visits_visitor_fkey', t.visitorId, authUsers.id, 'cascade'),
  index('profile_visits_card_time_idx').on(t.cardId,t.visitedAt),
  index('profile_visits_visitor_idx').on(t.visitorId),
  pgPolicy('service role full access on profile_visits', {for:'all', to:serviceRole, using:sql`true`, withCheck:sql`true`}),
]);
