import { boolean, index, integer, jsonb, pgTable, text, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, isOwner, jsonbDefault, publicPolicy, serviceRolePolicy, tsvector, tstz } from '../_shared';

// owner: persona. Also read by services/memory (agent_id, name, description,
// active, updated_at + search_personas_fts) — see OWNERS.md.
export const personaAgents = pgTable(
  'persona_agents',
  {
    userId: uuid('user_id').primaryKey(),
    agentId: text('agent_id').notNull().unique('persona_agents_agent_id_key'),
    derivationIndex: integer('derivation_index').notNull().unique('persona_agents_derivation_index_key'),
    publicKey: text('public_key').notNull(),
    name: text('name').notNull(),
    agentHandle: text('agent_handle'),
    description: text('description').notNull().default(''),
    capabilities: jsonb('capabilities').default(jsonbDefault('[]')),
    profile: jsonb('profile').default(jsonbDefault('{}')),
    webhookUrl: text('webhook_url'),
    active: boolean('active').default(true),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
    briefDocId: text('brief_doc_id'),
    briefDocUrl: text('brief_doc_url'),
    briefDocRevisionId: text('brief_doc_revision_id'),
    briefContent: text('brief_content'),
    // Maintained by trigger persona_agents_search_vector_trigger (migration 0000).
    searchVector: tsvector('search_vector'),
    autoExtractTodos: boolean('auto_extract_todos').notNull().default(true),
  },
  (t) => [
    fk('persona_agents_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    index('persona_agents_search_vector_idx').using('gin', t.searchVector),
    serviceRolePolicy('persona_agents'),
    publicPolicy('Users can read own persona', { for: 'select', using: isOwner('user_id') }),
    publicPolicy('Users can update own persona', { for: 'update', using: isOwner('user_id') }),
    // "Public read persona agents" (using true) was dropped in 0001: it let the
    // anon key read every persona's brief_content, profile and webhook_url.
  ],
);
