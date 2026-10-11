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
