import { sql } from 'drizzle-orm';
import { index, jsonb, pgTable, text, unique, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, isOwner, jsonbDefault, publicPolicy, serviceRolePolicy, tstz } from '../_shared';

// owner: persona — third-party connections (OAuth tokens, Telegram) and the
// profile data scraped from them.

const ownRead = (name: string) => publicPolicy(name, { for: 'select', using: isOwner('user_id') });
const ownDelete = (name: string) => publicPolicy(name, { for: 'delete', using: isOwner('user_id') });

export const apiTokens = pgTable(
  'api_tokens',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    provider: text('provider').notNull(),
    accessToken: text('access_token').notNull(),
    refreshToken: text('refresh_token'),
    expiresAt: tstz('expires_at'),
    scopes: text('scopes'),
    rawData: jsonb('raw_data').default(jsonbDefault('{}')),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('api_tokens_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    unique('api_tokens_user_id_provider_key').on(t.userId, t.provider),
    serviceRolePolicy('api_tokens'),
    ownRead('Users can read own tokens'),
    publicPolicy('Users can insert own tokens', { for: 'insert', withCheck: isOwner('user_id') }),
    publicPolicy('Users can update own tokens', { for: 'update', using: isOwner('user_id') }),
    ownDelete('Users can delete own tokens'),
  ],
);

// RLS on, no policies: only the service role touches OAuth state.
export const oauthPendingState = pgTable(
  'oauth_pending_state',
  {
    state: text('state').primaryKey(),
    userId: uuid('user_id').notNull(),
    provider: text('provider').notNull(),
    codeVerifier: text('code_verifier'),
    createdAt: tstz('created_at').defaultNow(),
    expiresAt: tstz('expires_at').default(sql`(now() + '00:15:00'::interval)`),
  },
  (t) => [fk('oauth_pending_state_user_id_fkey', t.userId, authUsers.id, 'cascade')],
).enableRLS();

export const telegramLinks = pgTable(
  'telegram_links',
  {
    userId: uuid('user_id').primaryKey(),
    chatId: text('chat_id').notNull().unique('telegram_links_chat_id_key'),
    linkedAt: tstz('linked_at').defaultNow(),
  },
  (t) => [
    fk('telegram_links_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    // Duplicates the unique constraint's index; kept because prod has it.
    index('telegram_links_chat_idx').on(t.chatId),
    serviceRolePolicy('telegram_links'),
    ownRead('Users read own telegram link'),
    ownDelete('Users delete own telegram link'),
  ],
);

export const telegramChatHistory = pgTable(
  'telegram_chat_history',
  {
    conversationId: text('conversation_id').primaryKey(),
    userId: uuid('user_id').notNull(),
    messages: jsonb('messages').notNull().default(jsonbDefault('[]')),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('telegram_chat_history_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    index('telegram_chat_history_user_idx').on(t.userId),
    serviceRolePolicy('telegram_chat_history'),
    ownRead('Users read own telegram history'),
  ],
);

export const linkedinProfiles = pgTable(
  'linkedin_profiles',
  {
    userId: uuid('user_id').primaryKey(),
    profileUrl: text('profile_url'),
    scrapedAt: tstz('scraped_at'),
    rawProfile: jsonb('raw_profile').notNull().default(jsonbDefault('{}')),
    rawPosts: jsonb('raw_posts').notNull().default(jsonbDefault('[]')),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('linkedin_profiles_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    index('linkedin_profiles_scraped_at_idx').on(t.scrapedAt.desc().nullsFirst()),
    serviceRolePolicy('linkedin_profiles'),
    ownRead('Users read own linkedin profile'),
    ownDelete('Users delete own linkedin profile'),
  ],
);

export const twitterProfiles = pgTable(
  'twitter_profiles',
  {
    userId: uuid('user_id').primaryKey(),
    handle: text('handle'),
    scrapedAt: tstz('scraped_at'),
    rawTweets: jsonb('raw_tweets').notNull().default(jsonbDefault('[]')),
    facts: jsonb('facts').notNull().default(jsonbDefault('[]')),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('twitter_profiles_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    index('twitter_profiles_scraped_at_idx').on(t.scrapedAt.desc().nullsFirst()),
    serviceRolePolicy('twitter_profiles'),
    ownRead('Users read own twitter profile'),
    ownDelete('Users delete own twitter profile'),
  ],
);

export const githubProfiles = pgTable(
  'github_profiles',
  {
    userId: uuid('user_id').primaryKey(),
    username: text('username'),
    rawRepos: jsonb('raw_repos').notNull().default(jsonbDefault('[]')),
    skills: jsonb('skills').notNull().default(jsonbDefault('[]')),
    projects: jsonb('projects').notNull().default(jsonbDefault('[]')),
    syncedAt: tstz('synced_at'),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('github_profiles_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    index('github_profiles_synced_at_idx').on(t.syncedAt.desc().nullsFirst()),
    serviceRolePolicy('github_profiles'),
    ownRead('Users read own github profile'),
    ownDelete('Users delete own github profile'),
  ],
);
