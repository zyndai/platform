import { sql } from 'drizzle-orm';
import { check, index, pgPolicy, text, uniqueIndex, uuid } from 'drizzle-orm/pg-core';
import { serviceRole, tstz } from '../../lib/shared';
import { cards } from './_schema';

// owner: cards — Zynd Companion browser extension (docs/plans/ZYND_COMPANION_PLAN.md). One row per
// paired browser. Written and read only by cards-api (services/companion.py); service-role only.

// The token itself is never stored, only its SHA-256, so a database read cannot be replayed. The
// owner is the lower-cased card owner email, the same key the owner-home routes use, so the table
// works on the xmfj and aafo projects alike. A device is dead once revoked_at is set, or 90 days
// after last_used_at (checked in code, so the limit can change without a migration).
export const companionDevices = cards.table(
  'companion_devices',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    ownerEmail: text('owner_email').notNull(),
    tokenHash: text('token_hash').notNull(),
    label: text('label').notNull().default(''),
    createdAt: tstz('created_at').notNull().defaultNow(),
    lastUsedAt: tstz('last_used_at').notNull().defaultNow(),
    revokedAt: tstz('revoked_at'),
  },
  (t) => [
    check('companion_devices_label_check', sql`char_length(label) <= 80`),
    uniqueIndex('companion_devices_token_hash_key').on(t.tokenHash),
    index('companion_devices_owner_idx').on(t.ownerEmail).where(sql`revoked_at IS NULL`),
    pgPolicy('service role full access on companion_devices', {
      as: 'permissive', for: 'all', to: serviceRole, using: sql`true`, withCheck: sql`true`,
    }),
  ],
);
