import assert from 'node:assert/strict';
import { test } from 'node:test';
import pg from 'pg';
import { memoryTarget, sameDatabase } from '../lib/memory-target';
import { migrateMemory } from '../scripts/migrate-memory';
import { HISTORIES, selectedHistories } from '../scripts/projects';

const env = { MEMORY_DATABASE_URL: 'postgresql://memory:secret@localhost:5544/memory' };

test('shared histories retain their order and never select memory', () => {
  assert.deepEqual(HISTORIES.map((h) => h.name), ['identity', 'persona', 'cards']);
  assert.deepEqual(selectedHistories([]), [...HISTORIES]);
  assert.deepEqual(selectedHistories(['--project', 'cards']).map((h) => h.name), ['cards']);
  assert.throws(() => selectedHistories(['--project', 'memory']), /unknown --project/);
});

test('memory requires its own URL and refuses shared targets before connecting', () => {
  assert.throws(() => memoryTarget({ DATABASE_URL: env.MEMORY_DATABASE_URL }), /never falls back/);
  for (const ref of ['aafoguuvmaxymrtnfafn', 'xmfjvixclgqcmjmtecwv']) {
    assert.throws(() => memoryTarget({ MEMORY_DATABASE_URL: `postgresql://postgres@db.${ref}.supabase.co/postgres` }), /Refusing/);
    assert.throws(() => memoryTarget({ MEMORY_DATABASE_URL: `postgresql://postgres.${ref}@pooler.supabase.com/postgres` }), /Refusing/);
  }
  assert.throws(() => memoryTarget({ ...env, DATABASE_URL: env.MEMORY_DATABASE_URL.replace('memory:secret', 'other:password') }), /different database/);
  assert.throws(() => memoryTarget({ MEMORY_DATABASE_URL: 'https://localhost/memory' }), /Postgres URL/);
  for (const key of ['host', 'hostaddr', 'port', 'dbname', 'user', 'service']) {
    assert.throws(() => memoryTarget({ MEMORY_DATABASE_URL: `${env.MEMORY_DATABASE_URL}?${key}=other` }), /cannot override/);
  }
  assert.equal(memoryTarget(env), env.MEMORY_DATABASE_URL);
  assert.equal(sameDatabase('postgres://a@LOCALHOST/db', 'postgresql://b@localhost:5432/db?sslmode=require'), true);
  assert.equal(sameDatabase('postgres://a@localhost/aafo', env.MEMORY_DATABASE_URL), false);
});

function mockClient(shared = false) {
  const calls: string[] = [];
  return {
    calls,
    client: {
      async connect() { calls.push('connect'); },
      async end() { calls.push('end'); },
      async query(sql: string) {
        calls.push(sql);
        return { rows: [{ has: sql.includes('persona_agents') && shared }] };
      },
    } as unknown as pg.Client,
  };
}

test('memory runner refuses shared catalog even through an unrecognized endpoint', async () => {
  const { client, calls } = mockClient(true);
  await assert.rejects(migrateMemory(['--yes'], env, client, async () => { assert.fail('must not migrate'); }), /shared database/);
  assert.equal(calls.at(-1), 'end');
});

test('memory runner defaults to read-only dry run and rejects shared runner flags', async () => {
  const { client, calls } = mockClient();
  await migrateMemory([], env, client, async () => { assert.fail('dry run must not migrate'); });
  assert.equal(calls.at(-1), 'end');
  assert.ok(calls.slice(1, -1).every((sql) => sql.startsWith('select')));
  await assert.rejects(migrateMemory(['--project', 'cards'], env, client), /Usage/);
});

test('memory apply uses only its independent migrator and closes on failure', async () => {
  const { client, calls } = mockClient();
  let applied = 0;
  await migrateMemory(['--yes'], env, client, async () => { applied++; });
  assert.equal(applied, 1);
  await assert.rejects(migrateMemory(['--yes'], env, client, async () => { throw new Error('rollback'); }), /rollback/);
  assert.equal(calls.at(-1), 'end');
});
