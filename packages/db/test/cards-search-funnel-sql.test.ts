import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import pg from 'pg';
import { migrationsFolder } from '../scripts/projects';

const server = process.env.CARDS_TEST_DATABASE_URL;

/** The named queries of the search-funnel section of docs/cards/s04-funnel.sql. */
function funnelQueries(): Record<string, string> {
  const sql = readFileSync(new URL('../../../docs/cards/s04-funnel.sql', import.meta.url), 'utf8');
  const section = sql.slice(sql.indexOf('-- Search funnel by search id'));
  const queries: Record<string, string> = {};
  for (const part of section.split(/^-- name: (\w+)$/m).slice(1).reduce<string[][]>((pairs, item, i, all) => {
    if (i % 2 === 0) pairs.push([item, all[i + 1]]);
    return pairs;
  }, [])) queries[part[0]] = part[1];
  return queries;
}

test('the search funnel queries answer from seeded events', { skip: !server }, async () => {
  const queries = funnelQueries();
  assert.deepEqual(Object.keys(queries).sort(), [
    'acceptance_by_source', 'connects_per_search', 'empty_share_by_via', 'suggestion_connect_rate', 'views_per_search']);

  const url = new URL(server!);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'tests require disposable local Postgres');
  const admin = new pg.Client({ connectionString: server });
  const name = `cards_funnel_test_${process.pid}_${Date.now()}`;
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
    await client.query("set request.jwt.claim.role='service_role'");

    const account = async (handle: string) => {
      const id = randomUUID();
      await client.query('insert into auth.users(id,email) values($1,$2)', [id, `${id}@test.invalid`]);
      await client.query(`insert into cards.agent_profile_cards(id,owner_user_id,owner_email,handle,status,card)
        values($1,$2,$3,$4,'published','{}')`, [`card-${handle}`, id, `${id}@test.invalid`, handle]);
      return { id, card: `card-${handle}` };
    };
    const [me, ada, bo, cy] = [await account('me'), await account('ada'), await account('bo'), await account('cy')];
    const connection = async (to: { id: string; card: string }, status: string) => (await client.query(
      `insert into cards.connections(connection_key,requester_user_id,recipient_user_id,requester_card_id,recipient_card_id,status)
        values($1,$2,$3,$4,$5,$6) returning id`,
      [[me.id, to.id].sort().join(':'), me.id, to.id, me.card, to.card, status])).rows[0].id as string;
    const event = (name: string, meta: object, ageDays = 1, handle: string | null = null) => client.query(
      `insert into cards.card_events(event,handle,meta,ts) values($1,$2,$3,now() - ($4 || ' days')::interval)`,
      [name, handle, JSON.stringify(meta), String(ageDays)]);

    const s1 = randomUUID(), s2 = randomUUID(), s3 = randomUUID(), s4 = randomUUID(), s5 = randomUUID();
    // memory: s1 found people and led to an accepted request; s2 found nobody; s3 is a name lookup
    // that fell back to a text search (two events, one id) and led to a pending request and an invite.
    await event('search', { n: 5, top: [], filters: [], text: true, search_id: s1, via: 'memory' });
    await event('search', { n: 0, top: [], filters: [], text: true, search_id: s2, via: 'memory' });
    await event('search', { n: 0, top: [], filters: [], text: true, search_id: s3, via: 'memory' });
    await event('search', { n: 3, top: [], filters: [], text: true, search_id: s3, via: 'memory' });
    await event('search', { n: 2, top: [], filters: [], text: true, search_id: s4, via: 'web' });
    await event('search', { n: 1, top: [], filters: [], text: true, search_id: s5, via: 'mcp' });
    await event('search', { n: 4, top: [], filters: [], text: true });                     // from before search ids existed
    await event('search', { n: 9, top: [], filters: [], text: true, search_id: randomUUID(), via: 'web' }, 40);  // too old
    const accepted = await connection(ada, 'accepted');
    const pending = await connection(bo, 'pending');
    await event('search_result_action', { search_id: s1, rank: 1, source: 'card', action: 'connect', connection_id: accepted }, 1, 'ada');
    await event('search_result_action', { search_id: s3, rank: 2, source: 'zynd', action: 'connect', connection_id: pending }, 1, 'bo');
    await event('search_result_action', { search_id: s3, rank: 4, source: 'linkedin', action: 'invite', invite_id: randomUUID() }, 1, 'grace');
    await event('view', { endpoint: 'profile-page', search_id: s4, rank: 1 }, 1, 'ada');
    await event('view', { endpoint: 'profile-page', search_id: s4, rank: 2 }, 1, 'bo');
    await event('view', { endpoint: 'profile-page' }, 1, 'cy');                            // not from a search
    // suggestions
    const impression = (surface: string, action: string | null, candidate = ada) => client.query(
      `insert into cards.card_suggestion_impressions(card_id,candidate_card_id,surface,action) values($1,$2,$3,$4)`,
      [me.card, candidate.card, surface, action]);
    await impression('digest', 'connect'); await impression('digest', null, bo); await impression('digest', 'hide', cy);
    await impression('owner_home', 'not_relevant'); await impression('owner_home', null, bo);

    const run = async (queryName: string) => (await client.query(queries[queryName])).rows;
    const by = <T extends Record<string, unknown>>(rows: T[], key: keyof T) => Object.fromEntries(rows.map((r) => [String(r[key]), r]));

    const empty = by(await run('empty_share_by_via'), 'via');
    assert.deepEqual(
      { searches: Number(empty.memory.searches), empty: Number(empty.memory.empty_searches), share: Number(empty.memory.empty_share) },
      { searches: 4, empty: 2, share: 0.5 });                                              // events, not search ids
    assert.equal(Number(empty.web.searches), 1);                                           // the 40-day-old one is out
    assert.equal(Number(empty['(before via)'].searches), 1);

    const connects = by(await run('connects_per_search'), 'via');
    assert.deepEqual(
      { searches: Number(connects.memory.searches), connects: Number(connects.memory.connects),
        invites: Number(connects.memory.invites), withConnect: Number(connects.memory.searches_with_a_connect),
        perSearch: Number(connects.memory.connects_per_search) },
      { searches: 3, connects: 2, invites: 1, withConnect: 2, perSearch: 0.667 });         // s3's two events are one search
    assert.equal(Number(connects.web.connects), 0);
    assert.equal(connects['(before via)'], undefined);                                     // no search id, nothing to join

    const acceptance = by(await run('acceptance_by_source'), 'source');
    assert.deepEqual(
      { card: [Number(acceptance.card.requests), Number(acceptance.card.accepted), Number(acceptance.card.accepted_per_request)],
        zynd: [Number(acceptance.zynd.requests), Number(acceptance.zynd.accepted), Number(acceptance.zynd.accepted_per_request)] },
      { card: [1, 1, 1], zynd: [1, 0, 0] });
    assert.equal(acceptance.linkedin, undefined);                                          // an invite is not a request

    const views = by(await run('views_per_search'), 'via');
    assert.deepEqual(
      { searches: Number(views.web.searches), views: Number(views.web.profile_views), withView: Number(views.web.searches_with_a_view),
        perSearch: Number(views.web.views_per_search) },
      { searches: 1, views: 2, withView: 1, perSearch: 2 });
    assert.equal(Number(views.memory.profile_views), 0);

    const suggestions = by(await run('suggestion_connect_rate'), 'surface');
    assert.deepEqual(
      { shown: Number(suggestions.digest.shown), connected: Number(suggestions.digest.connected),
        dismissed: Number(suggestions.digest.dismissed), rate: Number(suggestions.digest.connect_rate) },
      { shown: 3, connected: 1, dismissed: 1, rate: 0.333 });
    assert.deepEqual(
      { shown: Number(suggestions.owner_home.shown), connected: Number(suggestions.owner_home.connected),
        dismissed: Number(suggestions.owner_home.dismissed) },
      { shown: 2, connected: 0, dismissed: 1 });
  } finally {
    await client.end();
    await admin.query(`drop database ${name} with (force)`);
    await admin.end();
  }
});
