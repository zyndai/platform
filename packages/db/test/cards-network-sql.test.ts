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
    assert.equal((await client.query('select count(*)::int as n from drizzle.__cards_migrations')).rows[0].n, 24);
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
    const sendDm = async (user: string, connection: string, clientId: string, content: string) =>
      (await client.query('select cards.network_send_dm($1,$2,$3,$4) as result', [user, connection, clientId, content])).rows[0].result;
    const sendGroup = async (user: string, groupId: string, clientId: string, content: string) =>
      (await client.query('select cards.network_send_group_message($1,$2,$3,$4) as result', [user, groupId, clientId, content])).rows[0].result;
    const inbox = async (user: string) =>
      (await client.query('select cards.network_inbox($1) as result', [user])).rows[0].result;
    const readDm = async (user: string, connection: string, before: number | null = null, after: number | null = null) =>
      (await client.query('select cards.network_dm_messages($1,$2,$3,$4,50) as result', [user, connection, before, after])).rows[0].result;
    const readGroup = async (user: string, groupId: string) =>
      (await client.query('select cards.network_group_messages($1,$2,null,null,50) as result', [user, groupId])).rows[0].result;
    const threadFor = async (connection: string) =>
      (await client.query('select id from cards.dm_threads where connection_id=$1', [connection])).rows[0].id as string;
    const canSubscribe = async (user: string, topic: string) => {
      await client.query("select set_config('request.jwt.claim.sub',$1,false)", [user]);
      return (await client.query('select cards.network_can_subscribe($1) as ok', [topic])).rows[0].ok as boolean;
    };

    await t.test('DM sequence, idempotency, unread and inbox summary stay consistent', async () => {
      const alice = await account();
      const bob = await account();
      const direct = (await client.query(`insert into cards.connections(connection_key,requester_user_id,recipient_user_id,requester_card_id,recipient_card_id,status)
        values($1,$2,$3,$4,$5,'accepted') returning id`, [[alice, bob].sort().join(':'), alice, bob, `card-${alice}`, `card-${bob}`])).rows[0].id as string;
      const clientId = randomUUID();
      const first = await sendDm(alice, direct, clientId, '  hello   bob  ');
      assert.equal(first.message.seq, 1);
      assert.equal(first.message.content, 'hello   bob');
      assert.equal(first.duplicate, false);

      const retry = await sendDm(alice, direct, clientId, 'hello bob');
      assert.equal(retry.duplicate, true);
      assert.equal(retry.message.id, first.message.id);
      assert.equal((await client.query('select count(*)::int as n from cards.dm_messages where thread_id=$1', [first.message.thread_id])).rows[0].n, 1);

      const reply = await sendDm(bob, direct, randomUUID(), 'hi alice');
      assert.equal(reply.message.seq, 2);

      const aliceInbox = await inbox(alice);
      const aliceConnection = aliceInbox.connections.find((row: { id: string }) => row.id === direct);
      assert.equal(aliceConnection.unread_count, 1);
      assert.equal(aliceConnection.last_message_preview, 'hi alice');
      assert.equal(aliceConnection.last_message_sender_user_id, bob);
      assert.equal(aliceConnection.partner.name, 'Zynd member');

      const page = await readDm(alice, direct);
      assert.deepEqual(page.messages.map((message: { seq: number }) => message.seq), [1, 2]);
      assert.equal(page.has_more, false);
      assert.equal(page.peer_last_read_seq, 2);
      // Reading history is side-effect free; the client marks read explicitly.
      assert.equal((await inbox(alice)).connections.find((row: { id: string }) => row.id === direct).unread_count, 1);
      assert.equal((await client.query('select cards.network_mark_read($1,$2,$3,$4) as result', [alice, 'dm', direct, 2])).rows[0].result.status, 'ok');
      assert.equal((await inbox(alice)).connections.find((row: { id: string }) => row.id === direct).unread_count, 0);
      assert.equal((await readDm(bob, direct)).peer_last_read_seq, 2);

      const older = await readDm(alice, direct, 2);
      assert.deepEqual(older.messages.map((message: { seq: number }) => message.seq), [1]);
      const newer = await readDm(alice, direct, null, 1);
      assert.deepEqual(newer.messages.map((message: { seq: number }) => message.seq), [2]);

      assert.equal((await client.query('select cards.network_mark_read($1,$2,$3,$4) as result', [bob, 'dm', direct, 2])).rows[0].result.status, 'ok');
      assert.equal((await inbox(bob)).connections.find((row: { id: string }) => row.id === direct).unread_count, 0);

      // The trigger published a private message event and inbox events.
      const thread = await threadFor(direct);
      assert.ok((await client.query("select 1 from realtime.messages where topic=$1 and event='message' and private", [`cards:dm:${thread}`])).rowCount);
      assert.ok((await client.query("select 1 from realtime.messages where topic=$1 and event='inbox' and private", [`cards:user:${alice}`])).rowCount);
      assert.ok((await client.query("select 1 from realtime.messages where topic=$1 and event='inbox' and private", [`cards:user:${bob}`])).rowCount);

      assert.equal(await canSubscribe(alice, `cards:dm:${thread}`), true);
      assert.equal(await canSubscribe(stranger, `cards:dm:${thread}`), false);
      assert.equal(await canSubscribe(alice, `cards:user:${alice}`), true);
      assert.equal(await canSubscribe(bob, `cards:user:${alice}`), false);

      // Older MCP callers omit client_id; the partial unique index must not
      // make that path fail.
      const noKey = (await client.query('select cards.network_send_dm($1,$2,null,$3) as result', [alice, direct, 'no idempotency key'])).rows[0].result;
      assert.equal(noKey.duplicate, false);
      assert.equal(noKey.message.seq, 3);
    });

    await t.test('group sequence and new-member read cursor', async () => {
      const groupId = await group();
      const invitation = await invite(groupId);
      assert.equal((await decide(guest, invitation)).status, 'accepted');
      const first = await sendGroup(owner, groupId, randomUUID(), 'welcome');
      assert.equal(first.message.seq, 1);
      assert.equal((await inbox(guest)).groups.find((row: { id: string }) => row.id === groupId).unread_count, 1);
      await readGroup(guest, groupId);
      assert.equal((await inbox(guest)).groups.find((row: { id: string }) => row.id === groupId).unread_count, 1);
      await client.query('select cards.network_mark_read($1,$2,$3,$4)', [guest, 'group', groupId, 1]);
      assert.equal((await inbox(guest)).groups.find((row: { id: string }) => row.id === groupId).unread_count, 0);

      const lateInvite = await invite(groupId, stranger);
      assert.equal((await decide(stranger, lateInvite)).status, 'accepted');
      // A new member starts at the current message count, not at zero.
      assert.equal((await inbox(stranger)).groups.find((row: { id: string }) => row.id === groupId).unread_count, 0);

      const second = await sendGroup(owner, groupId, randomUUID(), 'second');
      assert.equal(second.message.seq, 2);
      assert.equal((await inbox(guest)).groups.find((row: { id: string }) => row.id === groupId).unread_count, 1);
      assert.equal((await inbox(stranger)).groups.find((row: { id: string }) => row.id === groupId).unread_count, 1);
      const page = await readGroup(guest, groupId);
      assert.deepEqual(page.messages.map((message: { seq: number }) => message.seq), [1, 2]);
      assert.equal(await canSubscribe(guest, `cards:group:${groupId}`), true);
      assert.equal(await canSubscribe(stranger, `cards:group:${groupId}`), true);

      const noKey = (await client.query('select cards.network_send_group_message($1,$2,null,$3) as result', [owner, groupId, 'no group idempotency key'])).rows[0].result;
      assert.equal(noKey.duplicate, false);
      assert.equal(noKey.message.seq, 3);
    });

    await t.test('browser roles can authorize Realtime topics but cannot call messaging RPCs', async () => {
      assert.equal((await client.query("select has_schema_privilege('authenticated','cards','usage') as allowed")).rows[0].allowed, true);
      assert.equal((await client.query("select has_function_privilege('authenticated','cards.network_can_subscribe(text)','execute') as allowed")).rows[0].allowed, true);
      for (const signature of [
        'cards.network_inbox(uuid)',
        'cards.network_dm_messages(uuid,uuid,bigint,bigint,integer)',
        'cards.network_send_dm(uuid,uuid,uuid,text)',
        'cards.network_mark_read(uuid,text,uuid,bigint)',
      ]) {
        assert.equal((await client.query('select has_function_privilege($1,$2,\'execute\') as allowed', ['authenticated', signature])).rows[0].allowed, false);
      }
    });

    await t.test('browser database roles cannot call the service-only functions', async () => {
      for (const role of ['anon', 'authenticated']) {
        assert.equal((await client.query("select has_function_privilege($1,'cards.network_respond_invitation(uuid,uuid,text)','execute') as allowed", [role])).rows[0].allowed, false);
        assert.equal((await client.query("select has_function_privilege($1,'cards.network_create_group(uuid,text,text,text)','execute') as allowed", [role])).rows[0].allowed, false);
        // Schema usage for the Realtime authorization function must not expose
        // older default-PUBLIC helpers such as the destructive purge.
        assert.equal((await client.query("select has_function_privilege($1,'cards.purge_card_events(interval)','execute') as allowed", [role])).rows[0].allowed, false);
      }
      assert.equal((await client.query("select has_function_privilege('service_role','cards.purge_card_events(interval)','execute') as allowed")).rows[0].allowed, true);
      for (const table of ['dm_messages', 'dm_threads', 'dm_read_state', 'groups', 'group_messages', 'group_read_state']) {
        assert.equal((await client.query('select has_table_privilege($1,$2,\'select\') as allowed', ['authenticated', `cards.${table}`])).rows[0].allowed, false);
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
