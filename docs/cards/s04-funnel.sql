-- S04 funnel queries (run in Supabase SQL editor against aafo).
-- Privacy: first-party attribution only; no raw IPs/emails/message bodies.
-- Retention: DELETE FROM cards.card_events WHERE ts < now() - interval '180 days';
--   (also POST /internal/purge-card-events with CRON_SECRET).

-- Creators last 7 days by source/ref
SELECT coalesce(ref, '(none)') AS ref,
       coalesce(source, '(none)') AS source,
       count(*) AS cards
FROM cards.agent_profile_cards
WHERE created_at > now() - interval '7 days'
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Daily funnel
SELECT *
FROM cards.v_funnel_daily
WHERE day > current_date - 14
ORDER BY day DESC;

-- Agent fetches by endpoint
SELECT meta->>'endpoint' AS endpoint,
       actor_class,
       count(*)
FROM cards.card_events
WHERE event = 'agent_fetch'
  AND ts > now() - interval '7 days'
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Share → create (ref like card:alice)
SELECT ref, count(*) AS publishes
FROM cards.agent_profile_cards
WHERE created_at > now() - interval '30 days'
  AND ref LIKE 'card:%'
GROUP BY 1
ORDER BY 2 DESC;

-- ─────────────────────────────────────────────────────────────────────────────────────
-- Networking funnel: search -> people returned -> request -> accepted -> first message.
-- (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md §13)
--
-- `search` events come from GET /v1/agents/search (so find_people, the public Cards MCP
-- and the website's /find all count). They hold only {n, top handles, which filters were
-- used, whether free text was used}: no query text and no caller identity. Later stages
-- come straight from the Cards network tables. A search carries no user id, so this is a
-- daily RATE view, not per-person attribution.
-- ─────────────────────────────────────────────────────────────────────────────────────

-- Daily networking funnel, last 14 days
WITH days AS (
  SELECT d::date AS day FROM generate_series(current_date - 13, current_date, interval '1 day') AS d
),
searches AS (
  SELECT (ts AT TIME ZONE 'UTC')::date AS day,
         count(*)                                              AS searches,
         count(*) FILTER (WHERE (meta->>'n')::int = 0)         AS empty_searches,
         coalesce(sum((meta->>'n')::int), 0)                   AS people_returned
  FROM cards.card_events
  WHERE event = 'search' AND ts > now() - interval '14 days'
  GROUP BY 1
),
requested AS (
  SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS requested
  FROM cards.connections
  WHERE created_at > now() - interval '14 days'
  GROUP BY 1
),
accepted AS (
  SELECT (decided_at AT TIME ZONE 'UTC')::date AS day, count(*) AS accepted
  FROM cards.connections
  WHERE decided_at > now() - interval '14 days' AND status IN ('accepted', 'revoked')
  GROUP BY 1
),
first_message AS (
  SELECT (first_at AT TIME ZONE 'UTC')::date AS day, count(*) AS first_messages
  FROM (
    SELECT thread_id, min(created_at) AS first_at
    FROM cards.dm_messages
    GROUP BY thread_id
  ) t
  WHERE first_at > now() - interval '14 days'
  GROUP BY 1
)
SELECT days.day,
       coalesce(s.searches, 0)        AS searches,
       coalesce(s.empty_searches, 0)  AS empty_searches,
       coalesce(s.people_returned, 0) AS people_returned,
       coalesce(r.requested, 0)       AS requests,
       coalesce(a.accepted, 0)        AS accepted,
       coalesce(m.first_messages, 0)  AS first_messages,
       round(coalesce(r.requested, 0)::numeric / nullif(s.searches, 0), 3)  AS requests_per_search,
       round(coalesce(a.accepted, 0)::numeric / nullif(r.requested, 0), 3)  AS accepted_per_request
FROM days
LEFT JOIN searches      s ON s.day = days.day
LEFT JOIN requested     r ON r.day = days.day
LEFT JOIN accepted      a ON a.day = days.day
LEFT JOIN first_message m ON m.day = days.day
ORDER BY days.day DESC;

-- Searches that found nobody, by which filters were used (is the parser/fallback failing?)
SELECT meta->'filters' AS filters,
       (meta->>'text')::boolean AS used_free_text,
       count(*) AS empty_searches
FROM cards.card_events
WHERE event = 'search' AND (meta->>'n')::int = 0 AND ts > now() - interval '14 days'
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Request -> accept latency, and how many accepted connections ever exchange a message
SELECT count(*)                                                                AS accepted_connections,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM cards.dm_threads t
         JOIN cards.dm_messages m ON m.thread_id = t.id
         WHERE t.connection_id = c.id))                                        AS ever_messaged,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY decided_at - created_at)    AS median_time_to_accept
FROM cards.connections c
WHERE status = 'accepted' AND created_at > now() - interval '30 days';
