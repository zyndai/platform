import { sql } from 'drizzle-orm';
import { boolean, check, index, jsonb, pgTable, text, uniqueIndex, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, isOwner, jsonbDefault, publicPolicy, serviceRolePolicy, tstz } from '../_shared';
import { personaGroups } from './groups';

// owner: persona — chat history, brief todos, published pages.

export const chatMessages = pgTable(
  'chat_messages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    conversationId: text('conversation_id').notNull(),
    role: text('role').notNull(),
    content: text('content').notNull(),
    actions: jsonb('actions').default(jsonbDefault('[]')),
    createdAt: tstz('created_at').defaultNow(),
    actionSummary: jsonb('action_summary').default(jsonbDefault('[]')),
  },
  (t) => [
    fk('chat_messages_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    serviceRolePolicy('chat_messages'),
    publicPolicy('Users can read own messages', { for: 'select', using: isOwner('user_id') }),
  ],
);

export const briefTodos = pgTable(
  'brief_todos',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    title: text('title').notNull(),
    sourceText: text('source_text'),
    done: boolean('done').notNull().default(false),
    doneAt: tstz('done_at'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    groupId: uuid('group_id'),
    assignedByUserId: uuid('assigned_by_user_id'),
  },
  (t) => [
    fk('brief_todos_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    fk('brief_todos_group_id_fkey', t.groupId, personaGroups.id, 'cascade'),
    fk('brief_todos_assigned_by_user_id_fkey', t.assignedByUserId, authUsers.id, 'set null'),
    index('brief_todos_group_idx').on(t.groupId),
    index('brief_todos_user_idx').on(t.userId, t.done, t.createdAt.desc().nullsFirst()),
    uniqueIndex('brief_todos_user_title_uniq').on(t.userId, t.title).where(sql`done = false`),
    serviceRolePolicy('brief_todos', { withCheck: true }),
    publicPolicy('Users can read own brief todos', { for: 'select', using: isOwner('user_id') }),
    publicPolicy('Users can update own brief todos', { for: 'update', using: isOwner('user_id') }),
    publicPolicy('Users can delete own brief todos', { for: 'delete', using: isOwner('user_id') }),
    publicPolicy('Group members can read group todos', {
      for: 'select',
      using: sql`(group_id IS NOT NULL) AND is_persona_group_member(group_id)`,
    }),
  ],
);

export const publishedPages = pgTable(
  'published_pages',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    // No FK to auth.users in prod; kept that way.
    userId: uuid('user_id').notNull(),
    slug: text('slug').notNull().unique('published_pages_slug_key'),
    title: text('title').notNull(),
    format: text('format').notNull(),
    content: text('content').notNull(),
    visibility: text('visibility').notNull().default('unlisted'),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
    expiresAt: tstz('expires_at'),
  },
  (t) => [
    check('published_pages_format_check', sql`format IN ('html', 'markdown')`),
    check('published_pages_visibility_check', sql`visibility IN ('public', 'unlisted', 'private')`),
    index('published_pages_expires_idx').on(t.expiresAt).where(sql`expires_at IS NOT NULL`),
    // Duplicates the unique constraint's index; kept because prod has it.
    index('published_pages_slug_idx').on(t.slug),
    index('published_pages_user_idx').on(t.userId, t.createdAt.desc().nullsFirst()),
    serviceRolePolicy('published_pages'),
    publicPolicy('Public read for public pages', { for: 'select', using: sql`(visibility = 'public'::text)` }),
    publicPolicy('Users can CRUD own pages', { for: 'all', using: isOwner('user_id'), withCheck: isOwner('user_id') }),
  ],
);
