import { sql } from 'drizzle-orm';
import { index, jsonb, pgPolicy, text, uuid, vector } from 'drizzle-orm/pg-core';
import { authUsers, fk, serviceRole, tsvector, tstz } from '../../lib/shared';
import { cards } from './_schema';

// owner: cards. Moved from the dashboard's Supabase project (xmfj) — columns
// exactly as in xmfj prod on 2026-09-26, plus owner_user_id.
//
// Access: service role only. cards-api is the only reader/writer; there is
// deliberately no anon "public read published cards" policy (xmfj has one,
// inert there because xmfj revoked anon's table grants). The cards schema
// grants nothing to anon/authenticated at all (migration 0000).
export const agentProfileCards = cards.table(
  'agent_profile_cards',
  {
    id: text('id').primaryKey(),
    status: text('status').notNull().default('draft'),
    handleGithub: text('handle_github'),
    handleX: text('handle_x'),
    card: jsonb('card').notNull(),
    // cards.skill_names() is created in migration 0000.
    searchTsv: tsvector('search_tsv').generatedAlwaysAs(
      sql`to_tsvector('english'::regconfig, ((((((COALESCE(((card -> 'identity'::text) ->> 'name'::text), ''::text) || ' '::text) || COALESCE(((card -> 'identity'::text) ->> 'headline'::text), ''::text)) || ' '::text) || COALESCE((card ->> 'summary'::text), ''::text)) || ' '::text) || cards.skill_names(card)))`,
    ),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
    publishedAt: tstz('published_at'),
    handle: text('handle').unique('agent_profile_cards_handle_key'),
    embedding: vector('embedding', { dimensions: 1536 }),
    scrapeRaw: jsonb('scrape_raw'),
    userIntent: jsonb('user_intent'),
    ownerEmail: text('owner_email'),
    suggestedPosts: jsonb('suggested_posts'),
    claimTokenHash: text('claim_token_hash'),
    // NEW (not in xmfj): the owner's aafo user — the same id persona uses.
    // Backfilled by email at cutover, then set by cards-api on signed-in writes.
    // owner_email stays the ownership authority until Stage 2.
    ownerUserId: uuid('owner_user_id'),
  },
  (t) => [
    fk('agent_profile_cards_owner_user_id_fkey', t.ownerUserId, authUsers.id, 'set null'),
    index('agent_profile_cards_status_idx').on(t.status),
    index('agent_profile_cards_tsv_idx').using('gin', t.searchTsv),
    index('agent_profile_cards_embedding_hnsw_idx').using('hnsw', t.embedding.op('vector_cosine_ops')),
    index('idx_cards_owner_email').on(t.ownerEmail),
    index('agent_profile_cards_owner_user_id_idx').on(t.ownerUserId),
    // xmfj's agent_profile_cards_handle_idx is not recreated: it duplicates
    // the unique constraint's index.
    pgPolicy('service role full access on cards', {
      as: 'permissive',
      for: 'all',
      to: serviceRole,
      using: sql`true`,
      withCheck: sql`true`,
    }),
  ],
);
