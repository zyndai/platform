-- owner: cards
-- S04: daily funnel view over card_events. Retention:
--   DELETE FROM cards.card_events WHERE ts < now() - interval '180 days';
-- (also exposed as POST /internal/purge-card-events).
-- Rollback: DROP VIEW IF EXISTS cards.v_funnel_daily;
CREATE OR REPLACE VIEW cards.v_funnel_daily AS
SELECT
  (ts AT TIME ZONE 'UTC')::date AS day,
  count(*) FILTER (WHERE event = 'create_start') AS create_start,
  count(*) FILTER (WHERE event = 'create_publish') AS create_publish,
  count(*) FILTER (WHERE event = 'claim_done') AS claim_done,
  count(*) FILTER (WHERE event = 'fact_approved') AS fact_approved,
  count(*) FILTER (WHERE event = 'agent_fetch') AS agent_fetch,
  count(*) FILTER (WHERE event = 'share_click') AS share_click,
  count(DISTINCT session_hash) FILTER (WHERE event = 'view') AS view_sessions
FROM cards.card_events
GROUP BY 1;
