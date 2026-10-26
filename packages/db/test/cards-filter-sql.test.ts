import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder } from '../scripts/projects';

const server = process.env.CARDS_TEST_DATABASE_URL;

// cards.filter_cards (0030) is the database half of card search: a superset filter that cards-api
// then narrows with its exact rules, so what matters here is that it never drops a card they keep.
test('cards.filter_cards keeps every card a role, place or skill could match', { skip: !server }, async () => {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'tests require disposable local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `cards_filter_test_${process.pid}_${Date.now()}`;
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
    const put = (id: string, claimed: boolean, headline: string, location: string, skills: string[], embedding: string | null) =>
      client.query(
        `insert into cards.agent_profile_cards(id,handle,status,owner_email,card,embedding) values($1,$1,'published',$2,$3,$4)`,
        [id, claimed ? `${id}@test.invalid` : null,
         JSON.stringify({ identity: { headline, location }, skills: skills.map((s) => ({ name: s })) }), embedding]);
    await put('vc', true, 'Seed Investor', 'Gurgaon', ['Next.js'], vector);
    await put('designer', true, 'Designer', 'Pune, India', [], null);
    await put('partner', false, 'Venture partner', 'London', [], null);
    const ids = async (sql: string, args: unknown[] = []) =>
      (await client.query(`select id from cards.filter_cards(${sql})`, args)).rows.map((r) => r.id).sort();

    // role: one group, any of its spellings (synonyms are the caller's job)
    assert.deepEqual(await ids(`'[["investor","vc","venture"]]'::jsonb, '{}', '[]'::jsonb, null, true`), ['partner', 'vc']);
    // unclaimed cards only when asked for
    assert.deepEqual(await ids(`'[["venture"]]'::jsonb, '{}', '[]'::jsonb, null, false`), []);
    // place: any fragment, punctuation ignored
    assert.deepEqual(await ids(`'[]'::jsonb, '{india,gurgaon}', '[]'::jsonb, null, false`), ['designer', 'vc']);
    // skill: "Next.js" is found by the squashed word
    assert.deepEqual(await ids(`'[]'::jsonb, '{}', '[["nextjs"]]'::jsonb, null, false`), ['vc']);
    // every group is required
    assert.deepEqual(await ids(`'[["investor"]]'::jsonb, '{pune}', '[]'::jsonb, null, false`), []);
    // similarity comes back computed, null without a vector, and the most similar card comes first
    const sim = (await client.query(`select id, similarity from cards.filter_cards('[]'::jsonb, '{}', '[]'::jsonb, $1::extensions.vector, true)`, [vector])).rows;
    assert.equal(sim[0].id, 'vc');
    assert.ok(Math.abs(sim[0].similarity - 1) < 1e-6);
    assert.equal(sim[1].similarity, null);
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
