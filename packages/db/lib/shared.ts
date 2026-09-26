import { sql, type SQL } from 'drizzle-orm';
import { customType, foreignKey, pgPolicy, timestamp, type PgColumn } from 'drizzle-orm/pg-core';

export { authUsers, serviceRole } from 'drizzle-orm/supabase';

/** Postgres `tsvector`. Drizzle has no built-in type for it. */
export const tsvector = customType<{ data: string }>({
  dataType() {
    return 'tsvector';
  },
});

/** `timestamp with time zone`, the only timestamp type this database uses. */
export const tstz = (name: string) => timestamp(name, { withTimezone: true });

/** jsonb literal default, e.g. jsonbDefault('[]') → DEFAULT '[]'::jsonb */
export const jsonbDefault = (literal: '[]' | '{}') => sql.raw(`'${literal}'::jsonb`);

/**
 * A named FK. Constraint names must match prod (`<table>_<column>_fkey`,
 * the Postgres default), not Drizzle's own naming, or future diffs would try
 * to rename every FK.
 */
export const fk = (
  name: string,
  column: PgColumn,
  references: PgColumn,
  onDelete?: 'cascade' | 'set null',
) => {
  const constraint = foreignKey({ name, columns: [column], foreignColumns: [references] });
  return onDelete ? constraint.onDelete(onDelete) : constraint;
};

const isServiceRole = sql`(auth.role() = 'service_role'::text)`;

/**
 * The "service role full access" policy every persona table carries. It is
 * redundant (service_role bypasses RLS) but exists in prod, so the schema
 * mirrors it exactly: capitalised name on the older tables, lower-case on
 * the persona_group_* ones, and WITH CHECK only where prod has it.
 */
export const serviceRolePolicy = (
  table: string,
  opts: { withCheck?: boolean; lowerCase?: boolean } = {},
) =>
  pgPolicy(`${opts.lowerCase ? 'service' : 'Service'} role full access on ${table}`, {
    as: 'permissive',
    for: 'all',
    to: 'public',
    using: isServiceRole,
    ...(opts.withCheck ? { withCheck: isServiceRole } : {}),
  });

/** A policy for role `public`, the way every persona policy is declared. */
export const publicPolicy = (
  name: string,
  opts: { for: 'select' | 'insert' | 'update' | 'delete' | 'all'; using?: SQL; withCheck?: SQL },
) =>
  pgPolicy(name, {
    as: 'permissive',
    for: opts.for,
    to: 'public',
    ...(opts.using ? { using: opts.using } : {}),
    ...(opts.withCheck ? { withCheck: opts.withCheck } : {}),
  });

/** `auth.uid() = <column>` — the owner check most persona policies use. */
export const isOwner = (column: string) => sql.raw(`(auth.uid() = ${column})`);
