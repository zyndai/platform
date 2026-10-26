import { sql } from 'drizzle-orm';
import { boolean, check, index, jsonb, pgPolicy, primaryKey, real, text, uuid } from 'drizzle-orm/pg-core';
import { fk, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';
import { agentProfileCards } from './cards';

// owner: cards — people to meet (people search plan Phase 2). Written and read only by cards-api
// (services/suggestions.py); service-role only.

const access = (name: string) => pgPolicy(`service role full access on ${name}`, {
  as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
});

// Each claimed card's top people to meet, written by the nightly job (POST
// /internal/suggestions/refresh) so the digest and owner home read a row instead of searching.
// Replaced whole per card; who may be shown is re-checked when it is read.
export const cardSuggestions = cards.table(
  'card_suggestions',
  {
    cardId: text('card_id').notNull(),
    candidateCardId: text('candidate_card_id').notNull(),
    target: text('target').notNull().default(''),
    score: real('score').notNull(),
    why: jsonb('why').notNull().default(sql`'[]'::jsonb`),
    twoWay: boolean('two_way').notNull().default(false),
    computedAt: tstz('computed_at').notNull().defaultNow(),
  },
  (t) => [
    primaryKey({ name: 'card_suggestions_pkey', columns: [t.cardId, t.candidateCardId] }),
    fk('card_suggestions_card_id_fkey', t.cardId, agentProfileCards.id, 'cascade'),
    fk('card_suggestions_candidate_card_id_fkey', t.candidateCardId, agentProfileCards.id, 'cascade'),
    access('card_suggestions'),
  ],
);

// Who a surface showed to a card's owner, and what the owner did about it. The digest skips
// people it showed in the last two weeks (unless their score rose); hide and not_relevant are
// never suggested again; connect is set when the owner sends that person a request.
export const cardSuggestionImpressions = cards.table(
  'card_suggestion_impressions',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    cardId: text('card_id').notNull(),
    candidateCardId: text('candidate_card_id').notNull(),
    surface: text('surface').notNull(),
    score: real('score'),
    shownAt: tstz('shown_at').notNull().defaultNow(),
    action: text('action'),
  },
  (t) => [
    fk('card_suggestion_impressions_card_id_fkey', t.cardId, agentProfileCards.id, 'cascade'),
    fk('card_suggestion_impressions_candidate_card_id_fkey', t.candidateCardId, agentProfileCards.id, 'cascade'),
    check('card_suggestion_impressions_surface_check', sql`surface IN ('digest', 'owner_home', 'api')`),
    check('card_suggestion_impressions_action_check',
      sql`action IS NULL OR action IN ('viewed', 'connect', 'hide', 'not_relevant')`),
    index('card_suggestion_impressions_card_shown_idx').on(t.cardId, t.shownAt.desc()),
    index('card_suggestion_impressions_pair_idx').on(t.cardId, t.candidateCardId),
    access('card_suggestion_impressions'),
  ],
);
