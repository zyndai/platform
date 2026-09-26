import { boolean, index, integer, jsonb, pgTable, real, text, unique, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, isOwner, jsonbDefault, publicPolicy, serviceRolePolicy, tstz } from '../../lib/shared';

// owner: persona — contact enrichment cache and suggested-contact recipes.

const ownAll = (name: string) =>
  publicPolicy(name, { for: 'all', using: isOwner('user_id'), withCheck: isOwner('user_id') });
const svc = (table: string) => serviceRolePolicy(table, { withCheck: true });

export const enrichedContacts = pgTable(
  'enriched_contacts',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    cacheKey: text('cache_key').notNull(),
    employeeLinkedin: text('employee_linkedin'),
    email: text('email'),
    firstName: text('first_name'),
    lastName: text('last_name'),
    title: text('title'),
    companyName: text('company_name'),
    companyUrl: text('company_url'),
    phone: text('phone'),
    phoneType: text('phone_type'),
    hasEmail: boolean('has_email').default(false),
    hasPhone: boolean('has_phone').default(false),
    data: jsonb('data').default(jsonbDefault('{}')),
    source: text('source'),
    enrichedAt: tstz('enriched_at'),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('enriched_contacts_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    unique('enriched_contacts_user_id_cache_key_key').on(t.userId, t.cacheKey),
    index('enriched_contacts_user_created_idx').on(t.userId, t.createdAt.desc().nullsFirst()),
    index('enriched_contacts_user_email_idx').on(t.userId, t.email),
    index('enriched_contacts_user_linkedin_idx').on(t.userId, t.employeeLinkedin),
    svc('enriched_contacts'),
    ownAll('Users can CRUD own enriched contacts'),
  ],
);

export const enrichedCompanies = pgTable(
  'enriched_companies',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    cacheKey: text('cache_key').notNull(),
    companyName: text('company_name'),
    companyUrl: text('company_url'),
    linkedinUrl: text('linkedin_url'),
    industry: text('industry'),
    employeeCount: text('employee_count'),
    revenue: text('revenue'),
    city: text('city'),
    regionCode: text('region_code'),
    countryCode: text('country_code'),
    data: jsonb('data').default(jsonbDefault('{}')),
    source: text('source'),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('enriched_companies_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    unique('enriched_companies_user_id_cache_key_key').on(t.userId, t.cacheKey),
    index('enriched_companies_user_created_idx').on(t.userId, t.createdAt.desc().nullsFirst()),
    svc('enriched_companies'),
    ownAll('Users can CRUD own enriched companies'),
  ],
);

export const suggestedContacts = pgTable(
  'suggested_contacts',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: uuid('user_id').notNull(),
    cacheKey: text('cache_key').notNull(),
    recipe: text('recipe').notNull(),
    reason: text('reason'),
    score: real('score').default(0),
    rank: integer('rank').default(0),
    generatedAt: tstz('generated_at').defaultNow(),
    createdAt: tstz('created_at').defaultNow(),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('suggested_contacts_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    unique('suggested_contacts_user_id_cache_key_recipe_key').on(t.userId, t.cacheKey, t.recipe),
    index('suggested_contacts_user_rank_idx').on(t.userId, t.recipe, t.rank),
    svc('suggested_contacts'),
    ownAll('Users can CRUD own suggested contacts'),
  ],
);

export const suggestedContactRuns = pgTable(
  'suggested_contact_runs',
  {
    userId: uuid('user_id').primaryKey(),
    lastRunAt: tstz('last_run_at'),
    lastManualAt: tstz('last_manual_at'),
    status: text('status'),
    detail: text('detail'),
    updatedAt: tstz('updated_at').defaultNow(),
  },
  (t) => [
    fk('suggested_contact_runs_user_id_fkey', t.userId, authUsers.id, 'cascade'),
    svc('suggested_contact_runs'),
    publicPolicy('Users can read own suggestion run state', { for: 'select', using: isOwner('user_id') }),
  ],
);
