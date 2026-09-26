/**
 * Print the SQL that records migration 0000 (the baseline) as already applied,
 * WITHOUT running it. Use it once on a database that already has the persona
 * schema (prod aafo), then `npm run db:migrate` applies only what follows 0000.
 *
 *   npm run db:baseline-sql     # paste the output into the Supabase SQL editor
 *
 * The row matches exactly what drizzle-orm's migrator would have written:
 * sha256 of the migration file and the journal's `when` for it.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const journal = JSON.parse(readFileSync(join(root, 'migrations/meta/_journal.json'), 'utf8')) as {
  entries: { idx: number; tag: string; when: number }[];
};
const baseline = journal.entries[0];
if (!baseline?.tag.startsWith('0000_')) throw new Error('first journal entry is not a 0000_ baseline');

const sql = readFileSync(join(root, 'migrations', `${baseline.tag}.sql`), 'utf8');
const hash = createHash('sha256').update(sql).digest('hex');

console.log(`-- Marks ${baseline.tag} as applied on a database that ALREADY has that schema.
-- Run once, in the aafo SQL editor. Safe to re-run: it does nothing if any
-- migration is already recorded.
create schema if not exists drizzle;
create table if not exists drizzle.__drizzle_migrations (
  id serial primary key,
  hash text not null,
  created_at bigint
);
insert into drizzle.__drizzle_migrations (hash, created_at)
select '${hash}', ${baseline.when}
where not exists (select 1 from drizzle.__drizzle_migrations);
select id, hash, created_at from drizzle.__drizzle_migrations order by id;`);
