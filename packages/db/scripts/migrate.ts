/**
 * Apply pending migrations to DATABASE_URL.
 *
 *   npm run db:migrate                                # dry run, every history
 *   npm run db:migrate -- --project cards             # dry run, one history
 *   npm run db:migrate -- --project cards --yes       # apply
 *
 * Histories (identity, persona, cards) are independent: each has its own
 * folder and its own tracking table (drizzle.__<name>_migrations), and each
 * applies in its own transaction. Within a history, all pending migrations run
 * in ONE transaction: if one fails, none of that history's pending ones apply.
 *
 * Uses drizzle-orm's own migrator (same bookkeeping as `drizzle-kit migrate`)
 * but prints the real Postgres error, shows what is pending, and refuses to
 * run against the dashboard project or to re-run persona's baseline on a
 * database that already has it.
 */
import 'dotenv/config';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder, migrationsTable, readJournal, selectedHistories, type HistoryName } from './projects';

// The dashboard's Supabase project. These migrations must never touch it.
const FORBIDDEN_REFS = ['xmfjvixclgqcmjmtecwv'];

async function lastApplied(client: pg.Client, name: HistoryName): Promise<number | undefined> {
  const exists = await client.query(`select to_regclass($1) is not null as has`, [`drizzle.${migrationsTable(name)}`]);
  if (!exists.rows[0].has) return undefined;
  const res = await client.query(
    `select created_at from drizzle.${migrationsTable(name)} order by created_at desc limit 1`,
  );
  return res.rows[0] ? Number(res.rows[0].created_at) : undefined;
}

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error('DATABASE_URL is not set (see .env.example)');
  const target = new URL(url);
  const shown = `${target.username}@${target.hostname}:${target.port || 5432}${target.pathname}`;
  if (FORBIDDEN_REFS.some((ref) => url.includes(ref))) {
    throw new Error(`Refusing to migrate ${shown}: that is the dashboard (xmfj) project, not aafo.`);
  }
  const apply = process.argv.includes('--yes');
  const histories = selectedHistories(process.argv);

  const client = new pg.Client({ connectionString: url });
  await client.connect();
  try {
    console.log(`Target: ${shown}${apply ? '' : '   (dry run: add `-- --yes` to apply)'}\n`);
    for (const { name } of histories) {
      const folder = migrationsFolder(name);
      const journal = readJournal(folder);
      const last = await lastApplied(client, name);
      const pending = journal.entries.filter((e) => last === undefined || e.when > last);
      const appliedUpTo = last === undefined ? 'nothing' : journal.entries.filter((e) => e.when <= last).at(-1)?.tag;
      console.log(`[${name}] applied: ${appliedUpTo}; pending: ${pending.length ? pending.map((e) => e.tag).join(', ') : 'none'}`);
      if (pending.length === 0) continue;

      if (name === 'persona' && last === undefined) {
        const legacy = await client.query(`select to_regclass('drizzle.__drizzle_migrations') is not null as has`);
        if (legacy.rows[0].has) {
          throw new Error(
            'Found drizzle.__drizzle_migrations (the pre-split tracking table). Rename it first:\n' +
              '  alter table drizzle.__drizzle_migrations rename to __persona_migrations;',
          );
        }
        const existing = await client.query(`select to_regclass('public.persona_agents') is not null as has`);
        if (existing.rows[0].has) {
          throw new Error(
            "This database already has persona's tables but no persona migration history. persona's\n" +
              '0000 is the BASELINE of exactly those tables: record it with `npm run db:baseline-sql`\n' +
              '(see README.md), never run it here. Refusing.',
          );
        }
      }
      if (!apply) continue;
      await migrate(drizzle(client), {
        migrationsFolder: folder,
        migrationsSchema: 'drizzle',
        migrationsTable: migrationsTable(name),
      });
      console.log(`[${name}] applied ${pending.length} migration(s).`);
    }
  } finally {
    await client.end();
  }
}

main().catch((err) => {
  console.error(`\nMigration failed. The history being applied rolled back (one transaction).\n${err?.message ?? err}`);
  if (err?.cause) console.error(`Cause: ${err.cause.message ?? err.cause}`);
  process.exit(1);
});
