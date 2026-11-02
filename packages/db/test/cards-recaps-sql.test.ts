import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import pg from 'pg';

const server = process.env.CARDS_TEST_DATABASE_URL;

test('recap migration keeps browser roles out, deduplicates periods, and enforces card lifecycle', { skip: !server }, async () => {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'requires disposable local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `cards_recaps_test_${process.pid}_${Date.now()}`;
  await admin.connect();
  await admin.query(`create database ${name}`);
  url.pathname = `/${name}`;
  const client = new pg.Client({ connectionString: url.href });
  try {
    await client.connect();
    await admin.query('select pg_advisory_lock(7934021)');
    try { await client.query(readFileSync(new URL('supabase-stubs.sql', import.meta.url), 'utf8')); }
    finally { await admin.query('select pg_advisory_unlock(7934021)'); }
    // Rehearse 0034 with its only table dependency; no pgvector is needed for this migration.
    await client.query(`create schema cards; grant usage on schema cards to service_role;
      alter default privileges in schema cards grant all on tables to service_role;
      create table cards.agent_profile_cards(id text primary key);
      insert into cards.agent_profile_cards values('alice');`);
    await client.query(readFileSync(new URL('../cards/migrations/0034_builder_recaps.sql', import.meta.url), 'utf8'));
    const code = async (work: Promise<unknown>) => {
      try { await work; } catch (error) { return (error as { code?: string }).code; }
      return 'no error';
    };
    const put = (period: string, owner = 'alice@test.invalid') => client.query(`insert into cards.card_recaps(card_id,owner_email,period,snapshot)
      values('alice',$1,$2,'{"highlights":[]}') returning *`, [owner, period]);
    await client.query('set role service_role');
    const first = (await put('2026-10')).rows[0];
    assert.equal(first.published_at, null);
    assert.deepEqual(first.selected_ids, []);
    assert.equal(await code(put('2026-10')), '23505');
    assert.equal(await code(put('2026-13')), '23514');
    await put('2026-Q4');
    await client.query(`insert into cards.card_milestones(card_id,owner_email,kind,title,occurred_on)
      values('alice','alice@test.invalid','shipped','Launch','2026-10-01')`);
    assert.equal(await code(client.query(`insert into cards.card_milestones(card_id,owner_email,kind,title,occurred_on)
      values('alice','alice@test.invalid','mastered','Vue','2026-10-01')`)), '23514');
    await client.query('reset role');
    for (const role of ['anon', 'authenticated']) {
      await client.query(`set role ${role}`);
      for (const table of ['card_milestones', 'card_recaps']) {
        assert.equal(await code(client.query(`select * from cards.${table}`)), '42501');
      }
      await client.query('reset role');
    }
    const secured = await client.query(`select relname, relrowsecurity from pg_class
      where oid in ('cards.card_milestones'::regclass,'cards.card_recaps'::regclass)`);
    assert.ok(secured.rows.every((r) => r.relrowsecurity));
    // A later, explicitly approved card deletion must not leave detached public recaps.
    await client.query(`delete from cards.agent_profile_cards where id='alice'`);
    assert.equal((await client.query('select count(*)::int as n from cards.card_recaps')).rows[0].n, 0);
    assert.equal((await client.query('select count(*)::int as n from cards.card_milestones')).rows[0].n, 0);
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
