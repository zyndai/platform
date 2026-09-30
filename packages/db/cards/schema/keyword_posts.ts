import { sql } from 'drizzle-orm';
import { date, jsonb, pgPolicy, text } from 'drizzle-orm/pg-core';
import { jsonbDefault, serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';

// owner: cards. Shared daily cache of social posts per interest keyword.
// cards-api reads/writes this for GET /cards/by-handle/{handle}/suggested-posts.
export const keywordPosts = cards.table(
  'keyword_posts',
  {
    keyword: text('keyword').primaryKey(),
    fetchedOn: date('fetched_on').notNull(),
    posts: jsonb('posts').notNull().default(jsonbDefault('[]')),
    summary: text('summary').notNull().default(''),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  () => [
    pgPolicy('service role full access on keyword_posts', {
      as: 'permissive',
      for: 'all',
      to: serviceRole,
      using: sql`true`,
      withCheck: sql`true`,
    }),
  ],
);
