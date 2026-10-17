import assert from 'node:assert/strict';
import { test } from 'node:test';
import pg from 'pg';
import { migrateMemory } from '../scripts/migrate-memory';

const server = process.env.MEMORY_TEST_DATABASE_URL;
test('memory SQL applies independently, enforces consent uniqueness, and is repeatable', { skip: !server }, async () => {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'integration tests require local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `memory_test_${process.pid}_${Date.now()}`;
  await admin.connect();
  await admin.query(`create database ${name}`);
  url.pathname = `/${name}`;
  const client = new pg.Client({ connectionString: url.href });
  try {
    await client.connect();
    await client.query('create table public.users(id uuid primary key); create table public.assertions(id uuid primary key)');
    const env = { MEMORY_DATABASE_URL: url.href };
    await migrateMemory([], env);
    assert.equal((await client.query("select to_regclass('public.memory_plugin_consents') as table")).rows[0].table, null);
    await migrateMemory(['--yes'], env);
    await migrateMemory(['--yes'], env);
    assert.equal((await client.query('select count(*)::int as n from drizzle.__memory_migrations')).rows[0].n, 1);
    assert.equal((await client.query("select to_regclass('drizzle.__persona_migrations') as table")).rows[0].table, null);
    await client.query("insert into public.users values ('00000000-0000-0000-0000-000000000001')");
    const consent = await client.query(`insert into public.memory_plugin_consents
      (proposal_id,user_id,action,content_hash,nonce_hash,version,decision,status,expires_at)
      values (gen_random_uuid(),'00000000-0000-0000-0000-000000000001','save_memory','hash','nonce-hash',1,'approve','saved_privately',now()) returning id`);
    const values = ['00000000-0000-0000-0000-000000000001', consent.rows[0].id, 'Exact private text'];
    await client.query('insert into public.memory_plugin_facts(user_id,consent_id,text) values ($1,$2,$3)', values);
    await assert.rejects(client.query('insert into public.memory_plugin_facts(user_id,consent_id,text) values ($1,$2,$3)', values), { code: '23505' });
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
