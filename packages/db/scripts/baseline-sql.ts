/**
 * Print the SQL that records persona's migration 0000 (the baseline) as
 * already applied, WITHOUT running it. Use it once on a database that already
 * has persona's tables (prod aafo); afterwards `npm run db:migrate` applies
 * only what follows 0000.
 *
 *   npm run db:baseline-sql     # paste the output into the Supabase SQL editor
 *
 * The row is exactly what drizzle-orm's migrator would have written: the
 * sha256 of the migration file and the journal's `when` for it.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { migrationsFolder, migrationsTable, readJournal } from './projects';

const folder = migrationsFolder('persona');
const table = migrationsTable('persona');
const baseline = readJournal(folder).entries[0];
if (!baseline?.tag.startsWith('0000_')) throw new Error('first persona journal entry is not a 0000_ baseline');

const hash = createHash('sha256').update(readFileSync(join(folder, `${baseline.tag}.sql`), 'utf8')).digest('hex');

console.log(`-- Records persona's ${baseline.tag} as applied on a database that ALREADY has
-- persona's tables. Run once, in the aafo SQL editor. Safe to re-run.
create schema if not exists drizzle;
-- Earlier instructions used drizzle.__drizzle_migrations; carry it over if present.
do $$ begin
  if to_regclass('drizzle.__drizzle_migrations') is not null and to_regclass('drizzle.${table}') is null then
    alter table drizzle.__drizzle_migrations rename to ${table};
  end if;
end $$;
create table if not exists drizzle.${table} (
  id serial primary key,
  hash text not null,
  created_at bigint
);
insert into drizzle.${table} (hash, created_at)
select '${hash}', ${baseline.when}
where not exists (select 1 from drizzle.${table});
select id, hash, created_at from drizzle.${table} order by id;`);
