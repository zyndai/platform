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
    assert.equal((await client.query('select count(*)::int as n from drizzle.__cards_migrations')).rows[0].n, 30);
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

    await t.test('group memory, remembered messages and agent jobs stay scoped', async () => {
      const groupId = await group();
      assert.equal((await decide(guest, await invite(groupId))).status, 'accepted');
      const first = await sendGroup(owner, groupId, randomUUID(), 'Decision: ship the API on Friday');
      const vector = "array_fill(0.1::real, ARRAY[1536])::vector";
      const remembered = (await client.query(
        `select cards.network_group_memory_remember($1,$2,$3,$4,${vector}) as result`,
        [owner, groupId, first.message.id, 'remember-hash-1'],
      )).rows[0].result;
      assert.equal(remembered.memory.kind, 'fact');
      assert.equal(remembered.memory.source_message_id, first.message.id);

      const page = await readGroup(guest, groupId);
      assert.equal(page.messages[0].remembered, true);
      assert.equal(page.messages[0].memory_id, remembered.memory.id);

      const manual = (await client.query(
        'select cards.network_group_memory_add_fact($1,$2,$3,$4,null) as result',
        [owner, groupId, 'The launch owner is Alice', 'manual-hash-1'],
      )).rows[0].result;
      assert.equal(manual.memory.kind, 'fact');
      const repeated = (await client.query(
        'select cards.network_group_memory_add_fact($1,$2,$3,$4,null) as result',
        [owner, groupId, 'The launch owner is Alice', 'manual-hash-1'],
      )).rows[0].result;
      assert.equal(repeated.memory.id, manual.memory.id);

      const agentClientId = randomUUID();
      const agentReply = (await client.query(
        'select cards.network_send_agent_group_message($1,$2,$3,$4,$5) as result',
        [groupId, guest, 'Friday works for me.', first.message.id, agentClientId],
      )).rows[0].result;
      assert.equal(agentReply.message.sender_kind, 'agent');
      assert.equal(agentReply.message.agent_for_user_id, guest);
      assert.equal(agentReply.message.reply_to_message_id, first.message.id);
      const retriedReply = (await client.query(
        'select cards.network_send_agent_group_message($1,$2,$3,$4,$5) as result',
        [groupId, guest, 'Friday works for me.', first.message.id, agentClientId],
      )).rows[0].result;
      assert.equal(retriedReply.duplicate, true);
      assert.equal(retriedReply.message.id, agentReply.message.id);
      const guestRead = (await client.query(
        'select last_read_seq from cards.group_read_state where group_id=$1 and user_id=$2',
        [groupId, guest],
      )).rows[0];
      assert.ok(!guestRead || guestRead.last_read_seq < agentReply.message.seq);

      const queued = (await client.query(
        'select cards.network_enqueue_group_agent_replies($1,$2) as result',
        [first.message.id, [guest]],
      )).rows[0].result;
      assert.equal(queued.enqueued, 1);
      const job = (await client.query('select cards.network_claim_group_agent_job() as result')).rows[0].result;
      assert.equal(job.status, 'running');
      assert.equal(job.mentioned_user_id, guest);
      const retry = (await client.query('select cards.network_finish_group_agent_job($1,false,$2) as result', [job.id, 'temporary'])).rows[0].result;
      assert.equal(retry.status, 'pending');
      await client.query('update cards.group_agent_jobs set available_at=now() where id=$1', [job.id]);
      const retriedJob = (await client.query('select cards.network_claim_group_agent_job() as result')).rows[0].result;
      assert.equal(retriedJob.id, job.id);
      assert.equal(retriedJob.attempts, 2);
      assert.equal((await client.query('select cards.network_finish_group_agent_job($1,true,null) as result', [retriedJob.id])).rows[0].result.status, 'done');

      const summary = (await client.query(
        `select cards.network_group_memory_set_summary($1,$2,$3,$4,${vector},'{}'::jsonb) as result`,
        [groupId, 'The group is shipping the API on Friday.', 'summary-hash-1', first.message.seq],
      )).rows[0].result;
      assert.equal(summary.memory.kind, 'summary');
      const listed = (await client.query('select cards.network_group_memory_list($1,$2,30) as result', [owner, groupId])).rows[0].result;
      assert.equal(listed.summary.content, 'The group is shipping the API on Friday.');
      assert.equal(listed.facts.length, 2);
      const search = (await client.query(
        `select cards.network_group_memory_search($1,$2,${vector},8) as result`, [owner, groupId],
      )).rows[0].result;
      assert.ok(search.some((row: { kind: string }) => row.kind === 'summary'));
      assert.ok(search.some((row: { kind: string }) => row.kind === 'fact'));

      // A member who turned replies off is never queued.
      const otherGroup = await group();
      assert.equal((await decide(guest, await invite(otherGroup))).status, 'accepted');
      await client.query('insert into cards.group_agent_preferences(user_id,enabled) values($1,false) on conflict (user_id) do update set enabled=false', [guest]);
      const second = await sendGroup(owner, otherGroup, randomUUID(), 'Second group message');
      const skipped = (await client.query(
        'select cards.network_enqueue_group_agent_replies($1,$2) as result',
        [second.message.id, [guest]],
      )).rows[0].result;
      assert.equal(skipped.enqueued, 0);
      await client.query('delete from cards.group_agent_preferences where user_id=$1', [guest]);
    });

    await t.test('assistant replies keep up to 8000 characters while human messages stay at 4000', async () => {
      const groupId = await group();
      assert.equal((await decide(guest, await invite(groupId))).status, 'accepted');
      const ask = await sendGroup(owner, groupId, randomUUID(), '@guest write the launch plan');
      const reply = async (content: string, clientId = randomUUID()) => (await client.query(
        'select cards.network_send_agent_group_message($1,$2,$3,$4,$5) as result',
        [groupId, guest, content, ask.message.id, clientId],
      )).rows[0].result;

      // 0027 and earlier cut this at 4000. A real plan is Markdown, so keep its shape too.
      const plan = `## Plan\n\n${'1. Ship it carefully.\n'.repeat(260)}`.trim();
      assert.ok(plan.length > 4000 && plan.length < 8000);
      const full = await reply(plan);
      assert.equal(full.message.content.length, plan.length);
      assert.ok(full.message.content === plan, 'the Markdown plan is stored unchanged');
      assert.equal(full.message.sender_kind, 'agent');

      // Exactly the limit is stored untouched; one more is cut to the limit.
      const exact = await reply('a'.repeat(8000));
      assert.equal(exact.message.content.length, 8000);
      const overKey = randomUUID();
      const over = await reply('b'.repeat(8001), overKey);
      assert.equal(over.message.content.length, 8000);
      assert.ok(over.message.content === 'b'.repeat(8000));
      // Padding is trimmed before the cut, so it never eats into the limit.
      const padded = await reply(`   ${'c'.repeat(8000)}   `);
      assert.equal(padded.message.content.length, 8000);
      assert.ok(padded.message.content === 'c'.repeat(8000));

      // A retry with the same key returns the stored reply, not a second one.
      const clientId = randomUUID();
      const first = await reply('d'.repeat(7000), clientId);
      const again = await reply('d'.repeat(7000), clientId);
      assert.equal(again.duplicate, true);
      assert.equal(again.message.id, first.message.id);

      // Pages and the Realtime broadcast carry the whole reply.
      const stored = (await readGroup(guest, groupId)).messages.find((message: { id: string }) => message.id === over.message.id);
      assert.equal(stored.content.length, 8000);
      const broadcast = (await client.query(
        `select length(payload->'message'->>'content') as n, payload->'message'->>'client_id' as client_id
         from realtime.messages where topic=$1 and event='message' and payload->'message'->>'id'=$2`,
        [`cards:group:${groupId}`, over.message.id],
      )).rows[0];
      assert.equal(broadcast.n, 8000);
      // The web UI matches a streaming bubble to its saved reply by client_id (= the job id).
      assert.equal(stored.client_id, overKey);
      assert.equal(broadcast.client_id, overKey);

      // The inbox line is still one short preview, whatever the length.
      const preview = (await inbox(owner)).groups.find((row: { id: string }) => row.id === groupId).last_message_preview as string;
      assert.ok(preview.startsWith('AI: ') && preview.length <= 144);

      // Empty is still rejected, and a non-member's assistant still cannot write.
      assert.equal((await reply('   ')).status_code, 400);
      const outsider = (await client.query(
        'select cards.network_send_agent_group_message($1,$2,$3,null,null) as result', [groupId, stranger, 'hello'],
      )).rows[0].result;
      assert.equal(outsider.status_code, 403);

      // Human messages did not move: group messages and DMs still stop at 4000.
      const human = await sendGroup(owner, groupId, randomUUID(), 'h'.repeat(4001));
      assert.equal(human.message.content.length, 4000);
      const exactHuman = await sendGroup(owner, groupId, randomUUID(), 'k'.repeat(4000));
      assert.equal(exactHuman.message.content.length, 4000);
      const direct = await sendDm(owner, guestConnection, randomUUID(), 'm'.repeat(4001));
      assert.equal(direct.message.content.length, 4000);

      // Same grants as before: service only.
      for (const role of ['anon', 'authenticated']) {
        assert.equal((await client.query(
          "select has_function_privilege($1,'cards.network_send_agent_group_message(uuid,uuid,text,uuid,uuid)','execute') as allowed", [role],
        )).rows[0].allowed, false);
      }
      assert.equal((await client.query(
        "select has_function_privilege('service_role','cards.network_send_agent_group_message(uuid,uuid,text,uuid,uuid)','execute') as allowed",
      )).rows[0].allowed, true);
    });

    await t.test('browser roles can authorize Realtime topics but cannot call messaging RPCs', async () => {
      assert.equal((await client.query("select has_schema_privilege('authenticated','cards','usage') as allowed")).rows[0].allowed, true);
      assert.equal((await client.query("select has_function_privilege('authenticated','cards.network_can_subscribe(text)','execute') as allowed")).rows[0].allowed, true);
      for (const signature of [
        'cards.network_inbox(uuid)',
        'cards.network_dm_messages(uuid,uuid,bigint,bigint,integer)',
        'cards.network_send_dm(uuid,uuid,uuid,text)',
        'cards.network_mark_read(uuid,text,uuid,bigint)',
        'cards.network_send_agent_group_message(uuid,uuid,text,uuid,uuid)',
        'cards.network_enqueue_group_agent_replies(uuid,uuid[])',
        'cards.network_claim_group_agent_job()',
        'cards.network_finish_group_agent_job(uuid,boolean,text)',
        'cards.network_group_memory_search(uuid,uuid,vector,integer)',
        'cards.network_group_memory_remember(uuid,uuid,uuid,text,vector)',
        'cards.network_group_memory_add_fact(uuid,uuid,text,text,vector)',
        'cards.network_group_memory_set_summary(uuid,text,text,bigint,vector,jsonb)',
        'cards.network_group_memory_list(uuid,uuid,integer)',
        'cards.network_groups_needing_summary(integer,integer)',
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
