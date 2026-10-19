import 'dotenv/config';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { memoryTarget } from '../lib/memory-target';
import { readJournal, root } from './projects';

export async function migrateMemory(
  argv = process.argv.slice(2),
  env = process.env,
  client = new pg.Client({ connectionString: memoryTarget(env) }),
  applyMigrations = () => migrate(drizzle(client), {
    migrationsFolder: join(root, 'memory/migrations'),
    migrationsSchema: 'drizzle',
    migrationsTable: '__memory_migrations',
  }),
) {
  if (argv.some((arg) => arg !== '--yes')) throw new Error('Usage: npm run memory:migrate -- [--yes]');
  const target = new URL(memoryTarget(env));
  const apply = argv.includes('--yes');
  await client.connect();
  try {
    const shared = await client.query(`select
      to_regclass('public.persona_agents') is not null or
      to_regclass('cards.agent_profile_cards') is not null or
      to_regclass('drizzle.__identity_migrations') is not null or
      to_regclass('drizzle.__persona_migrations') is not null or
      to_regclass('drizzle.__cards_migrations') is not null as has`);
    if (shared.rows[0].has) throw new Error('Refusing memory migrations: shared database tables or migration history found.');
    console.log(`Memory target: ${target.hostname}:${target.port || 5432}${target.pathname}${apply ? '' : ' (dry run)'}`);
    const exists = await client.query("select to_regclass('drizzle.__memory_migrations') is not null as has");
    const result = exists.rows[0].has
      ? await client.query('select created_at from drizzle.__memory_migrations order by created_at desc limit 1')
      : { rows: [] };
    const last = result.rows[0] ? Number(result.rows[0].created_at) : undefined;
    const pending = readJournal(join(root, 'memory/migrations')).entries.filter((e) => last === undefined || e.when > last);
    console.log(`[memory] pending: ${pending.map((e) => e.tag).join(', ') || 'none'}`);
    if (apply && pending.length) await applyMigrations();
  } finally {
    await client.end();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  migrateMemory().catch((err) => {
    console.error(`Memory migration failed: ${err?.message ?? err}`);
    process.exitCode = 1;
  });
}
