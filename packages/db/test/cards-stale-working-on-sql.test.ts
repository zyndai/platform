import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder } from '../scripts/projects';

const server = process.env.CARDS_TEST_DATABASE_URL;

// 0035: working_on_updated_at is stamped by a trigger, so every writer of card->'working_on' is
// covered: cards-api's full-card writes and upserts, s10_save_section and companion_save_fields.
test('working_on_updated_at follows working_on on every write path', { skip: !server }, async () => {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'tests require disposable local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `cards_stale_test_${process.pid}_${Date.now()}`;
  await admin.connect();
  await admin.query(`create database ${name}`);
  url.pathname = `/${name}`;
  const client = new pg.Client({ connectionString: url.href });
  try {
    await client.connect();
    await admin.query('select pg_advisory_lock(7934021)');
    try {
      await client.query(readFileSync(new URL('supabase-stubs.sql', import.meta.url), 'utf8'));
    } finally { await admin.query('select pg_advisory_unlock(7934021)'); }
    await client.query('set search_path=public,extensions');
    await migrate(drizzle(client), {
      migrationsFolder: migrationsFolder('cards'), migrationsSchema: 'drizzle', migrationsTable: '__cards_migrations',
    });

    const put = (id: string, card: object) =>
      client.query(`insert into cards.agent_profile_cards(id,handle,status,owner_email,card) values($1,$1,'published','alice@test.invalid',$2)`,
        [id, JSON.stringify(card)]);
    const row = async (id: string) => (await client.query(
      `select working_on_updated_at as stamp,
              card ? 'working_on_updated_at' as has_mirror,
              card->'working_on_updated_at' is not distinct from to_jsonb(working_on_updated_at) as mirror_ok,
              working_on_updated_at > now() - interval '1 minute' as fresh,
              card
         from cards.agent_profile_cards where id=$1`, [id])).rows[0];
    // Stand-in for "this was stamped long ago": an explicit write the trigger keeps.
    const age = (id: string) =>
      client.query(`update cards.agent_profile_cards set working_on_updated_at = now() - interval '200 days' where id=$1`, [id]);
    const saveSection = (patch: object, expected: object) =>
      client.query('select cards.s10_save_section($1,$2,$3::jsonb,$4::jsonb)',
        ['alice@test.invalid', 'alice', JSON.stringify(patch), JSON.stringify(expected)]);

    // Publish (INSERT) stamps a non-empty list and mirrors it into the card JSON.
    await put('alice', { summary: 'Hi', working_on: ['Old'] });
    let r = await row('alice');
    assert.equal(r.fresh, true);
    assert.equal(r.mirror_ok, true);

    // An empty list has nothing to go stale: no stamp, no key.
    await put('empty', { summary: 'Hi', working_on: [] });
    r = await row('empty');
    assert.equal(r.stamp, null);
    assert.equal(r.has_mirror, false);

    // The editor's section save: changing working_on restamps, saving another section does not.
    await age('alice');
    await saveSection({ summary: 'Hello' }, { summary: 'Hi' });
    r = await row('alice');
    assert.equal(r.fresh, false);
    assert.equal(r.mirror_ok, true);
    await saveSection({ working_on: ['New'] }, { working_on: ['Old'] });
    r = await row('alice');
    assert.equal(r.fresh, true);
    assert.equal(r.mirror_ok, true);

    // The browser extension's write restamps too.
    await age('alice');
    await client.query('select cards.companion_save_fields($1,$2,$3::jsonb,$4::jsonb)',
      ['alice@test.invalid', 'alice', JSON.stringify({ working_on: ['New', 'Clip'] }), JSON.stringify({ working_on: ['New'] })]);
    assert.equal((await row('alice')).fresh, true);

    // cards-api full-card writes: a card JSON without the key, or with a stale copy of it, cannot
    // move the stamp while working_on is unchanged; the mirror is rewritten from the column.
    await age('alice');
    const before = (await row('alice')).stamp.getTime();
    const card = (await row('alice')).card;
    const { working_on_updated_at: _dropped, ...withoutKey } = card;
    await client.query(`update cards.agent_profile_cards set card=$1 where id='alice'`, [JSON.stringify(withoutKey)]);
    r = await row('alice');
    assert.equal(r.stamp.getTime(), before);
    assert.equal(r.mirror_ok, true);
    await client.query(`update cards.agent_profile_cards set card=$1 where id='alice'`,
      [JSON.stringify({ ...card, working_on_updated_at: '2099-01-01T00:00:00+00:00' })]);
    r = await row('alice');
    assert.equal(r.stamp.getTime(), before);
    assert.equal(r.mirror_ok, true);

    // PostgREST's upsert (save_card) re-sends the card; unchanged working_on keeps the stamp.
    const upsert = (c: object) => client.query(
      `insert into cards.agent_profile_cards(id,handle,status,card) values('alice','alice','published',$1)
       on conflict (id) do update set card = excluded.card, status = excluded.status`, [JSON.stringify(c)]);
    await upsert(withoutKey);
    assert.equal((await row('alice')).stamp.getTime(), before);
    await upsert({ ...withoutKey, working_on: ['Rewritten'] });
    assert.equal((await row('alice')).fresh, true);

    // Updates that never touch `card` skip the trigger.
    await age('alice');
    const aged = (await row('alice')).stamp.getTime();
    await client.query(`update cards.agent_profile_cards set status='private' where id='alice'`);
    assert.equal((await row('alice')).stamp.getTime(), aged);

    // The owner's confirm sets the column explicitly; it is kept, and never lands in the future.
    await client.query(`update cards.agent_profile_cards set working_on_updated_at = now() + interval '5 years' where id='alice'`);
    r = await row('alice');
    assert.equal(r.fresh, true);
    assert.ok(r.stamp.getTime() <= Date.now() + 60_000);
    assert.equal(r.mirror_ok, true);

    // A row from before this migration (column NULL, working_on set) stays unknown until its
    // working_on actually changes: other writes never invent a stamp for it.
    await client.query('alter table cards.agent_profile_cards disable trigger agent_profile_cards_working_on_stamp');
    await put('legacy', { summary: 'Old card', working_on: ['Something'] });
    await client.query('alter table cards.agent_profile_cards enable trigger agent_profile_cards_working_on_stamp');
    await client.query(`update cards.agent_profile_cards set card = card || '{"summary":"Edited"}' where id='legacy'`);
    r = await row('legacy');
    assert.equal(r.stamp, null);
    assert.equal(r.has_mirror, false);
    assert.equal(r.card.summary, 'Edited');

    // The API roles still cannot call the trigger function directly.
    for (const role of ['anon', 'authenticated']) {
      await client.query(`set role ${role}`);
      const denied = await client.query('select cards.stamp_working_on_updated_at()').then(() => 'no error', (e) => e.code);
      assert.equal(denied, '42501');
      await client.query('reset role');
    }
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
