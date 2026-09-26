/**
 * Apply pending migrations to DATABASE_URL.
 *
 *   npm run db:migrate            # dry run: shows the target and what would run
 *   npm run db:migrate -- --yes   # applies
 *
 * Uses drizzle-orm's own migrator (same bookkeeping as `drizzle-kit migrate`:
 * drizzle.__drizzle_migrations, one row per applied file), but unlike
 * drizzle-kit it prints the real Postgres error, lists what is pending, and
 * refuses to run against the dashboard project by mistake.
 *
 * All pending migrations run in ONE transaction: if any fails, none apply.
 */
import 'dotenv/config';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const MIGRATIONS = { migrationsFolder: join(root, 'migrations'), migrationsSchema: 'drizzle', migrationsTable: '__drizzle_migrations' };

// The dashboard's Supabase project. This package must never touch it.
const FORBIDDEN_REFS = ['xmfjvixclgqcmjmtecwv'];

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error('DATABASE_URL is not set (see .env.example)');
  const target = new URL(url);
  const shown = `${target.username}@${target.hostname}:${target.port || 5432}${target.pathname}`;
  if (FORBIDDEN_REFS.some((ref) => url.includes(ref))) {
    throw new Error(`Refusing to migrate ${shown}: that is the dashboard (xmfj) project, not aafo.`);
  }

  const journal = JSON.parse(readFileSync(join(MIGRATIONS.migrationsFolder, 'meta/_journal.json'), 'utf8')) as {
    entries: { tag: string; when: number }[];
  };

  const client = new pg.Client({ connectionString: url });
  await client.connect();
  try {
    const tracked = await client.query(
      `select created_at from drizzle.__drizzle_migrations order by created_at desc limit 1`,
    ).catch(() => ({ rows: [] as { created_at: string }[] }));
    const last = tracked.rows[0] ? Number(tracked.rows[0].created_at) : undefined;
    const pending = journal.entries.filter((e) => last === undefined || e.when > last);

    console.log(`Target:  ${shown}`);
    console.log(`Applied: ${last === undefined ? 'nothing yet (no drizzle.__drizzle_migrations table)' : `up to ${journal.entries.filter((e) => e.when <= last).at(-1)?.tag ?? '?'}`}`);
    if (pending.length === 0) {
      console.log('Pending: none. Nothing to do.');
      return;
    }
    console.log(`Pending: ${pending.map((e) => e.tag).join(', ')}`);
    if (last === undefined) {
      const existing = await client.query(`select to_regclass('public.persona_agents') is not null as has`);
      if (existing.rows[0]?.has) {
        throw new Error(
          'This database already has the persona schema but no migration history. 0000 is the\n' +
            'BASELINE of exactly that schema: mark it applied with `npm run db:baseline-sql`\n' +
            '(see README.md), never run it here. Refusing.',
        );
      }
    }
    if (!process.argv.includes('--yes')) {
      console.log('\nDry run. Re-run with `-- --yes` to apply.');
      return;
    }
    await migrate(drizzle(client), MIGRATIONS);
    console.log(`\nApplied ${pending.length} migration(s).`);
  } finally {
    await client.end();
  }
}

main().catch((err) => {
  console.error(`\nMigration failed — nothing was applied (single transaction).\n${err?.message ?? err}`);
  if (err?.cause) console.error(`Cause: ${err.cause.message ?? err.cause}`);
  process.exit(1);
});
