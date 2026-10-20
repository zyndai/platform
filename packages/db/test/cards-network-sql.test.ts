import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder } from '../scripts/projects';

const server = process.env.CARDS_TEST_DATABASE_URL;

test('Cards network migrations preserve invitation and membership invariants', { skip: !server }, async (t) => {
  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'tests require disposable local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `cards_network_test_${process.pid}_${Date.now()}`;
  await admin.connect();
  await admin.query(`create database ${name}`);
  url.pathname = `/${name}`;
  const client = new pg.Client({ connectionString: url.href });
  const connect = async () => {
    const connection = new pg.Client({ connectionString: url.href });
    await connection.connect();
    await connection.query("set request.jwt.claim.role='service_role'");
    return connection;
  };
  try {
    await client.connect();
    await admin.query('select pg_advisory_lock(7934021)');
    try {
      await client.query(readFileSync(new URL('supabase-stubs.sql', import.meta.url), 'utf8'));
    } finally { await admin.query('select pg_advisory_unlock(7934021)'); }
    await client.query('set search_path=public,extensions');
    const apply = () => migrate(drizzle(client), {
      migrationsFolder: migrationsFolder('cards'), migrationsSchema: 'drizzle', migrationsTable: '__cards_migrations',
    });
    await apply();
    await apply();
    assert.equal((await client.query('select count(*)::int as n from drizzle.__cards_migrations')).rows[0].n, 25);
    assert.equal((await client.query("select to_regclass('drizzle.__persona_migrations') as table")).rows[0].table, null);
    await client.query("set request.jwt.claim.role='service_role'");

    const account = async () => {
      const id = randomUUID();
      await client.query('insert into auth.users(id,email) values($1,$2)', [id, `${id}@test.invalid`]);
      await client.query(`insert into cards.agent_profile_cards(id,owner_user_id,owner_email,handle,status,card)
        values($1,$2,$3,$1,'published','{}')`, [`card-${id}`, id, `${id}@test.invalid`]);
      return id;
    };
    const owner = await account();
    const guest = await account();
    const stranger = await account();
    const link = async (user: string) => {
      const result = await client.query(`insert into cards.connections(connection_key,requester_user_id,recipient_user_id,requester_card_id,recipient_card_id,status)
        values($1,$2,$3,$4,$5,'accepted') returning id`, [[owner, user].sort().join(':'), owner, user, `card-${owner}`, `card-${user}`]);
      return result.rows[0].id;
    };
    const guestConnection = await link(guest);
    await link(stranger);
    const group = async () => (await client.query(
      "select cards.network_create_group($1,'Test group',null,'private') as result", [owner],
    )).rows[0].result.group.id as string;
    const invite = async (groupId: string, user = guest, expired = false) => (await client.query(
      `insert into cards.group_invitations(group_id,invitee_user_id,inviter_user_id,expires_at)
       values($1,$2,$3,clock_timestamp()+$4::interval) returning id`, [groupId, user, owner, expired ? '-1 day' : '7 days'],
    )).rows[0].id as string;
    const decide = async (user: string, invitation: string, decision = 'accept', db = client) => (await db.query(
      'select cards.network_respond_invitation($1,$2,$3) as result', [user, invitation, decision],
    )).rows[0].result;

    await t.test('group owner membership is created together with the group', async () => {
      const id = await group();
      const member = await client.query('select role from cards.group_members where group_id=$1 and user_id=$2', [id, owner]);
      assert.equal(member.rows[0].role, 'owner');
    });
    await t.test('expired invitation cannot add membership even without listing the inbox', async () => {
      const id = await group();
      const invitation = await invite(id, guest, true);
      assert.equal((await decide(guest, invitation)).error, 'Invitation expired');
      assert.equal((await client.query('select status from cards.group_invitations where id=$1', [invitation])).rows[0].status, 'expired');
      assert.equal((await client.query('select count(*)::int as n from cards.group_members where group_id=$1', [id])).rows[0].n, 1);
    });
    await t.test('only the invitee can accept and a retry never duplicates membership', async () => {
      const id = await group();
      const invitation = await invite(id);
      assert.equal((await decide(stranger, invitation)).status_code, 404);
      assert.equal((await decide(guest, invitation)).status, 'accepted');
      assert.equal((await decide(guest, invitation)).status_code, 409);
      assert.equal((await client.query('select count(*)::int as n from cards.group_members where group_id=$1', [id])).rows[0].n, 2);
    });
    await t.test('declining never adds membership', async () => {
      const id = await group();
      assert.equal((await decide(guest, await invite(id), 'decline')).status, 'declined');
      assert.equal((await client.query('select count(*)::int as n from cards.group_members where group_id=$1', [id])).rows[0].n, 1);
    });
    await t.test('revoked connections and archived groups cannot be joined', async () => {
      const id = await group();
      const invitation = await invite(id);
      await client.query("update cards.connections set status='revoked' where id=$1", [guestConnection]);
      assert.equal((await decide(guest, invitation)).status_code, 409);
      await client.query("update cards.connections set status='accepted' where id=$1", [guestConnection]);
      await client.query('update cards.groups set archived_at=now() where id=$1', [id]);
      assert.equal((await decide(guest, invitation)).status_code, 404);
    });
    await t.test('concurrent accept and decline cannot disagree with membership', async () => {
      const id = await group();
      const invitation = await invite(id);
      const other = await connect();
      try {
        const results = await Promise.all([decide(guest, invitation), decide(guest, invitation, 'decline', other)]);
        assert.equal(results.filter(result => !result.error).length, 1);
        const status = (await client.query('select status from cards.group_invitations where id=$1', [invitation])).rows[0].status;
        const count = (await client.query('select count(*)::int as n from cards.group_members where group_id=$1 and user_id=$2', [id, guest])).rows[0].n;
        assert.equal(count, status === 'accepted' ? 1 : 0);
      } finally { await other.end(); }
    });
    await t.test('two concurrent acceptances cannot take the same final group slot', async () => {
      const id = await group();
      for (let n = 0; n < 48; n++) {
        const user = await account();
        await client.query('insert into cards.group_members(group_id,user_id) values($1,$2)', [id, user]);
      }
      const first = await invite(id);
      const second = await invite(id, stranger);
      const other = await connect();
      try {
        const results = await Promise.all([decide(guest, first), decide(stranger, second, 'accept', other)]);
        assert.equal(results.filter(result => result.status === 'accepted').length, 1);
        assert.equal(results.filter(result => result.error === 'This group is full').length, 1);
        assert.equal((await client.query('select count(*)::int as n from cards.group_members where group_id=$1', [id])).rows[0].n, 50);
      } finally { await other.end(); }
    });
    await t.test('browser database roles cannot call the service-only functions', async () => {
      for (const role of ['anon', 'authenticated']) {
        assert.equal((await client.query("select has_function_privilege($1,'cards.network_respond_invitation(uuid,uuid,text)','execute') as allowed", [role])).rows[0].allowed, false);
        assert.equal((await client.query("select has_function_privilege($1,'cards.network_create_group(uuid,text,text,text)','execute') as allowed", [role])).rows[0].allowed, false);
      }
      await client.query("set request.jwt.claim.role='authenticated'");
      await assert.rejects(client.query("select cards.network_create_group($1,'forbidden',null,'private')", [owner]), { code: '42501' });
    });
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
