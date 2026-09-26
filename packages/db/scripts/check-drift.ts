/**
 * Drift check: does the real database's public schema equal what our
 * migrations build?
 *
 *   npm run db:drift -- --expected <catalog-file | postgres-url> --scratch <postgres-url> [--upto <tag>]
 *
 * --expected  Prod's schema. Either a file holding the output of
 *             scripts/catalog.sql (raw text, or the Supabase SQL editor's
 *             JSON/CSV export), or a postgres URL to query read-only.
 * --scratch   A throwaway Postgres server (NOT Supabase, NOT prod). A temp
 *             database is created there, loaded with test/supabase-stubs.sql
 *             and every migration, catalogued, then dropped.
 * --upto      Only apply migrations up to and including this tag, e.g. to
 *             check prod before a new migration is applied to it.
 *
 * Exit code 0 = no drift. 1 = drift (the differing entries are printed).
 */
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const catalogSql = readFileSync(join(root, 'scripts/catalog.sql'), 'utf8');

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? undefined : process.argv[i + 1];
}

async function catalogOf(url: string): Promise<string> {
  const client = new pg.Client({ connectionString: url });
  await client.connect();
  try {
    await client.query('begin transaction read only');
    const res = await client.query(catalogSql);
    await client.query('commit');
    return String(Object.values(res.rows[0])[0] ?? '');
  } finally {
    await client.end();
  }
}

/** Accept raw text, the SQL editor's JSON export, or its CSV export. */
function decodeExport(raw: string): string {
  const t = raw.trim();
  if (t.startsWith('[')) return String(Object.values(JSON.parse(t)[0])[0]);
  if (t.startsWith('string_agg')) {
    const body = t.slice(t.indexOf('\n') + 1).trim();
    return body.startsWith('"') ? body.slice(1, -1).replace(/""/g, '"') : body;
  }
  return t;
}

const ENTRY = /^(0 project|extension|column|constraint|index|trigger|function|rls|policy|view|publication|grant) \| /;

/** Split the catalog into entries (a function body spans several lines) and drop the ones that differ for reasons that aren't drift. */
function entries(catalog: string): Set<string> {
  const out: string[] = [];
  for (const line of catalog.split('\n')) {
    if (ENTRY.test(line) || out.length === 0) out.push(line);
    else out[out.length - 1] += '\n' + line;
  }
  return new Set(
    out
      .map((e) => e.trimEnd())
      .filter(
        (e) =>
          !e.startsWith('0 project |') && // which project, not schema
          !e.startsWith('extension |') && // Supabase-managed
          !e.startsWith('publication | supabase_realtime_messages_publication') && // daily partitions
          !/^constraint \| [^|]+ \| NOT NULL /.test(e), // Postgres 18+ lists NOT NULL as constraints; 17 doesn't
      ),
  );
}

async function buildScratch(serverUrl: string, upto?: string): Promise<string> {
  const dbName = `zynd_drift_${process.pid}_${Date.now()}`;
  const admin = new pg.Client({ connectionString: serverUrl });
  await admin.connect();
  await admin.query(`create database ${dbName}`);
  const dbUrl = new URL(serverUrl);
  dbUrl.pathname = `/${dbName}`;

  const work = mkdtempSync(join(tmpdir(), 'zynd-drift-'));
  try {
    const db = new pg.Client({ connectionString: dbUrl.toString() });
    await db.connect();
    await db.query(readFileSync(join(root, 'test/supabase-stubs.sql'), 'utf8'));
    await db.end();

    // Copy migrations so --upto can trim the journal without touching the repo.
    const migrations = join(work, 'migrations');
    cpSync(join(root, 'migrations'), migrations, { recursive: true });
    if (upto) {
      const journalPath = join(migrations, 'meta/_journal.json');
      const journal = JSON.parse(readFileSync(journalPath, 'utf8'));
      const cut = journal.entries.findIndex((e: { tag: string }) => e.tag === upto);
      if (cut === -1) throw new Error(`--upto ${upto}: no such migration`);
      journal.entries = journal.entries.slice(0, cut + 1);
      writeFileSync(journalPath, JSON.stringify(journal, null, 2));
    }
    const client = new pg.Client({ connectionString: dbUrl.toString() });
    await client.connect();
    try {
      await migrate(drizzle(client), {
        migrationsFolder: migrations,
        migrationsSchema: 'drizzle',
        migrationsTable: '__drizzle_migrations',
      });
    } finally {
      await client.end();
    }
    return await catalogOf(dbUrl.toString());
  } finally {
    rmSync(work, { recursive: true, force: true });
    await admin.query(`drop database if exists ${dbName} with (force)`);
    await admin.end();
  }
}

async function main() {
  const expected = arg('expected');
  const scratch = arg('scratch');
  if (!expected || !scratch) {
    console.error('usage: npm run db:drift -- --expected <catalog-file|postgres-url> --scratch <postgres-url> [--upto <tag>]');
    process.exit(2);
  }
  const prod = entries(
    /^postgres(ql)?:\/\//.test(expected) ? await catalogOf(expected) : decodeExport(readFileSync(expected, 'utf8')),
  );
  const built = entries(await buildScratch(scratch, arg('upto')));

  const onlyProd = [...prod].filter((e) => !built.has(e)).sort();
  const onlyBuilt = [...built].filter((e) => !prod.has(e)).sort();
  if (onlyProd.length === 0 && onlyBuilt.length === 0) {
    console.log(`No drift: ${prod.size} catalog entries match.`);
    return;
  }
  for (const e of onlyProd) console.log(`- only in the real database:\n  ${e.replace(/\n/g, '\n  ')}`);
  for (const e of onlyBuilt) console.log(`+ only in the migrations:\n  ${e.replace(/\n/g, '\n  ')}`);
  console.log(`\nDRIFT: ${onlyProd.length} entries only in the database, ${onlyBuilt.length} only in the migrations.`);
  process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
