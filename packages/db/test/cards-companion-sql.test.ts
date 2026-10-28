import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder } from '../scripts/projects';

const server = process.env.CARDS_TEST_DATABASE_URL;

// cards.companion_devices and cards.companion_save_fields (0032) are what a browser extension's
// device token can reach: a table of hashed tokens, and a write that may touch two card fields.
test('companion_save_fields writes only working_on and exploring, and only for the owner', { skip: !server }, async () => {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'tests require disposable local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `cards_companion_test_${process.pid}_${Date.now()}`;
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

    const vector = `[${[1, ...Array(1535).fill(0)].join(',')}]`;
    const put = (id: string, owner: string, status: string, card: object) =>
      client.query(
        `insert into cards.agent_profile_cards(id,handle,status,owner_email,card,embedding) values($1,$1,$2,$3,$4,$5)`,
        [id, status, owner, JSON.stringify(card), vector]);
    await put('alice', 'Alice@Test.invalid', 'published', { summary: 'Hi', working_on: ['Old'] });
    await put('merged', 'carol@test.invalid', 'merged', {});
    const save = (email: string, handle: string, patch: object, expected: object) =>
      client.query('select cards.companion_save_fields($1,$2,$3::jsonb,$4::jsonb) as card',
        [email, handle, JSON.stringify(patch), JSON.stringify(expected)]);
    const code = async (run: Promise<unknown>) => {
      try { await run; } catch (e) { return (e as { code?: string }).code; }
      return 'no error';
    };
    const stored = async () => (await client.query(`select card, embedding is null as no_vector from cards.agent_profile_cards where id='alice'`)).rows[0];

    // A card that never had `exploring` reads as an empty list, so the first clip does not conflict.
    const clip = [{ url: 'https://a.test/x', title: 'x', kind: 'link', note: '', added_at: '2026-10-27T00:00:00Z' }];
    const first = await save('alice@test.invalid', 'alice', { exploring: clip }, { exploring: [] });
    assert.deepEqual(first.rows[0].card.exploring, clip);
    assert.equal(first.rows[0].card.summary, 'Hi');           // the rest of the card is untouched
    assert.equal((await stored()).no_vector, false);          // search text does not use exploring: vector kept

    // working_on feeds search, so saving it clears the vector (cards-api then re-embeds).
    await save('alice@test.invalid', 'alice', { working_on: ['New', 'Old'] }, { working_on: ['Old'] });
    assert.deepEqual((await stored()).card.working_on, ['New', 'Old']);
    assert.equal((await stored()).no_vector, true);

    // The editor (or another browser) changed the field since it was read: 40001, nothing written.
    assert.equal(await code(save('alice@test.invalid', 'alice', { working_on: ['Late'] }, { working_on: ['Old'] })), '40001');
    assert.deepEqual((await stored()).card.working_on, ['New', 'Old']);

    // Only those two fields, only arrays, and no more than 20 entries.
    assert.equal(await code(save('alice@test.invalid', 'alice', { summary: 'Hacked' }, { summary: 'Hi' })), '22023');
    assert.equal(await code(save('alice@test.invalid', 'alice', { identity: {} }, { identity: {} })), '22023');
    assert.equal(await code(save('alice@test.invalid', 'alice', { exploring: 'x' }, { exploring: clip })), '22023');
    assert.equal(await code(save('alice@test.invalid', 'alice', { exploring: Array(21).fill(clip[0]) }, { exploring: clip })), '22023');
    assert.equal(await code(save('alice@test.invalid', 'alice', { exploring: [] }, {})), '22023');
    assert.equal((await stored()).card.summary, 'Hi');

    // Not the owner, unknown handle, merged card: 42501.
    assert.equal(await code(save('bob@test.invalid', 'alice', { working_on: [] }, { working_on: ['New', 'Old'] })), '42501');
    assert.equal(await code(save('alice@test.invalid', 'nobody', { working_on: [] }, { working_on: [] })), '42501');
    assert.equal(await code(save('carol@test.invalid', 'merged', { working_on: [] }, { working_on: [] })), '42501');

    // The API roles cannot call it or read the table; the service role can.
    for (const role of ['anon', 'authenticated']) {
      await client.query(`set role ${role}`);
      assert.equal(await code(save('alice@test.invalid', 'alice', { working_on: [] }, { working_on: ['New', 'Old'] })), '42501');
      assert.equal(await code(client.query('select count(*)::int as n from cards.companion_devices')), '42501');
      await client.query('reset role');
    }
    await client.query('set role service_role');
    await client.query(`insert into cards.companion_devices(owner_email,token_hash,label) values('alice@test.invalid','h1','Chrome')`);
    assert.equal((await client.query('select count(*)::int as n from cards.companion_devices')).rows[0].n, 1);
    await client.query('reset role');

    // One row per token hash, and a label cannot be a novel.
    assert.equal(await code(client.query(`insert into cards.companion_devices(owner_email,token_hash) values('alice@test.invalid','h1')`)), '23505');
    assert.equal(await code(client.query(`insert into cards.companion_devices(owner_email,token_hash,label) values('alice@test.invalid','h2',$1)`, ['x'.repeat(81)])), '23514');
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
