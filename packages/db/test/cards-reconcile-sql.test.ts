import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder } from '../scripts/projects';

const server = process.env.CARDS_TEST_DATABASE_URL;
const catalogSql = readFileSync(new URL('../scripts/catalog.sql', import.meta.url), 'utf8');

async function scratch(run: (client: pg.Client) => Promise<void>) {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'local disposable databases only');
  const admin = new pg.Client({ connectionString: url.href });
  const name = `cards_reconcile_${process.pid}_${Date.now()}`;
  await admin.connect();
  await admin.query(`create database ${name}`);
  url.pathname = `/${name}`;
  const client = new pg.Client({ connectionString: url.href });
  try {
    await client.connect();
    // Supabase roles are cluster-wide, even though test databases are separate.
    await admin.query('select pg_advisory_lock(7934021)');
    try {
      await client.query(readFileSync(new URL('supabase-stubs.sql', import.meta.url), 'utf8'));
    } finally { await admin.query('select pg_advisory_unlock(7934021)'); }
    await client.query('set search_path=public,extensions');
    await run(client);
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
}

async function apply(client: pg.Client, upto?: number) {
  let folder = migrationsFolder('cards');
  const work = upto === undefined ? undefined : mkdtempSync(join(tmpdir(), 'cards-reconcile-prefix-'));
  try {
    if (work) {
      const journal = JSON.parse(readFileSync(join(folder, 'meta/_journal.json'), 'utf8'));
      journal.entries = journal.entries.filter((entry: { idx: number }) => entry.idx <= upto!);
      mkdirSync(join(work, 'meta'));
      writeFileSync(join(work, 'meta/_journal.json'), JSON.stringify(journal));
      for (const entry of journal.entries) cpSync(join(folder, `${entry.tag}.sql`), join(work, `${entry.tag}.sql`));
      folder = work;
    }
    await migrate(drizzle(client), { migrationsFolder: folder, migrationsSchema: 'drizzle', migrationsTable: '__cards_migrations' });
  } finally { if (work) rmSync(work, { recursive: true, force: true }); }
}

const dailyColumns = ['day', 'event', 'actor_class', 'n'];
const totalColumns = ['day', 'create_start', 'create_publish', 'claim_done', 'fact_approved', 'agent_fetch', 'share_click', 'view_sessions'];
async function columns(client: pg.Client, view: string) {
  return (await client.query('select column_name from information_schema.columns where table_schema=\'cards\' and table_name=$1 order by ordinal_position', [view])).rows.map(row => row.column_name);
}

// Reproduce the observed older live shape in a DISPOSABLE fixture only. These
// drops never run against Supabase and are not part of the repair migrations.
async function liveShape(client: pg.Client) {
  await apply(client, 19);
  await client.query(`
    alter table cards.agent_profile_cards add digest_opt_out boolean not null default false,
      add last_looking_for_nudge_on date, add last_owner_digest_on date, add looking_for_expires_at timestamptz;
    alter table cards.card_events drop constraint card_events_actor_class_check,
      alter actor_class drop not null, alter actor_class drop default;
    drop view cards.v_funnel_daily;
    create view cards.v_funnel_daily as
      select (date_trunc('day',ts) at time zone 'utc')::date as day,event,actor_class,count(*) as n
      from cards.card_events group by 1,2,3;
    create view cards.reconcile_dependent_fixture as select day,event,n from cards.v_funnel_daily;
    insert into cards.agent_profile_cards(id,card,digest_opt_out,last_owner_digest_on)
      values('preserved','{"identity":{"name":"Synthetic member"}}',true,'2026-10-01');
    insert into cards.card_events(event,actor_class) values('view','human');
  `);
}

test('Cards reconciliation preserves the live view contract and every existing row', { skip: !server }, async () => {
  await scratch(async client => {
    await liveShape(client);
    const before = await client.query('select to_jsonb(c) as value from cards.agent_profile_cards c order by id');
    const oid = (await client.query("select 'cards.v_funnel_daily'::regclass::oid as value")).rows[0].value;
    const definition = (await client.query("select pg_get_viewdef('cards.v_funnel_daily'::regclass,true) as value")).rows[0].value;
    await apply(client);
    await apply(client);
    assert.deepEqual((await client.query('select to_jsonb(c) as value from cards.agent_profile_cards c order by id')).rows, before.rows);
    assert.equal((await client.query("select 'cards.v_funnel_daily'::regclass::oid as value")).rows[0].value, oid);
    assert.equal((await client.query("select pg_get_viewdef('cards.v_funnel_daily'::regclass,true) as value")).rows[0].value, definition);
    assert.deepEqual(await columns(client, 'v_funnel_daily'), dailyColumns);
    assert.deepEqual(await columns(client, 'v_funnel_daily_totals'), totalColumns);
    assert.equal((await client.query('select sum(n)::int as n from cards.reconcile_dependent_fixture')).rows[0].n, 1);
    assert.equal((await client.query('select count(*)::int as n from cards.card_events')).rows[0].n, 1);
    await assert.rejects(client.query("insert into cards.card_events(event,actor_class) values('view','invalid')"), { code: '23514' });
    await assert.rejects(client.query("insert into cards.card_events(event,actor_class) values('view',null)"), { code: '23502' });
    assert.equal((await client.query("select count(*)::int as n from information_schema.columns where table_schema='cards' and table_name='agent_profile_cards' and column_name in ('digest_opt_out','last_looking_for_nudge_on','last_owner_digest_on','looking_for_expires_at')")).rows[0].n, 4);
    assert.equal((await client.query("select has_schema_privilege('anon','cards','usage') as allowed")).rows[0].allowed, false);
    assert.equal((await client.query("select to_regprocedure('cards.purge_card_events(interval)') is not null as present")).rows[0].present, true);
  });
});

test('historical fresh databases retain their totals view under its explicit name', { skip: !server }, async () => {
  await scratch(async client => {
    await apply(client, 20);
    const oid = (await client.query("select 'cards.v_funnel_daily'::regclass::oid as value")).rows[0].value;
    await apply(client);
    assert.equal((await client.query("select 'cards.v_funnel_daily_totals'::regclass::oid as value")).rows[0].value, oid);
    assert.deepEqual(await columns(client, 'v_funnel_daily'), dailyColumns);
    assert.deepEqual(await columns(client, 'v_funnel_daily_totals'), totalColumns);
  });
});

test('unexpected legacy event classifications abort all pending migrations without data loss', { skip: !server }, async () => {
  await scratch(async client => {
    await liveShape(client);
    await client.query("insert into cards.card_events(event,actor_class) values('view','legacy-unknown-value')");
    await assert.rejects(apply(client), (error: unknown) => error instanceof Error
      && 'cause' in error && (error.cause as { code?: string }).code === '23514');
    assert.equal((await client.query("select actor_class from cards.card_events where actor_class='legacy-unknown-value'")).rowCount, 1);
    assert.equal((await client.query('select count(*)::int as n from drizzle.__cards_migrations')).rows[0].n, 20);
    assert.equal((await client.query("select to_regprocedure('cards.network_create_group(uuid,text,text,text)') is null as absent")).rows[0].absent, true);
  });
});

test('catalog ignores ACL ordering but detects a real permission change', { skip: !server }, async () => {
  await scratch(async client => {
    await apply(client);
    await client.query('create function cards.acl_order_fixture() returns int language sql as $$ select 1 $$; grant execute on function cards.acl_order_fixture() to public,service_role');
    const catalog = async () => String(Object.values((await client.query(catalogSql)).rows[0])[0])
      .split('\n').find(line => line.startsWith('function | cards.acl_order_fixture('));
    const before = await catalog();
    assert.ok(before?.includes('| acl={=X/postgres,postgres=X/postgres,service_role=X/postgres}'));
    await client.query('revoke execute on function cards.acl_order_fixture() from public,service_role; grant execute on function cards.acl_order_fixture() to public,service_role');
    assert.equal(await catalog(), before);
    await client.query('revoke execute on function cards.acl_order_fixture() from public');
    assert.notEqual(await catalog(), before);
  });
});
