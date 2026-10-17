-- owner: cards
-- Reconcile the reviewed live Cards drift without deleting or rewriting rows.
-- The deployed v_funnel_daily (day,event,actor_class,n) keeps its OID, definition,
-- grants, and dependents. The historical wide totals view gets an explicit name
-- only when replaying the old migration shape; that shape is absent on live aafo.
-- Rollback: revert app code, retain metadata/views/functions and event constraints.
-- Do not drop owner columns or message data, or replace the deployed daily view.

DO $$
BEGIN
  -- Fail instead of coercing unexpected legacy data or losing its original value.
  IF EXISTS (SELECT 1 FROM cards.card_events WHERE actor_class IS NULL
             OR actor_class NOT IN ('human','ai_agent','search_bot','unknown')) THEN
    RAISE EXCEPTION 'Review legacy event classifications before migrating' USING ERRCODE='23514';
  END IF;
END $$;
--> statement-breakpoint
ALTER TABLE cards.card_events ALTER COLUMN actor_class SET DEFAULT 'unknown';
ALTER TABLE cards.card_events ALTER COLUMN actor_class SET NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='cards.card_events'::regclass
                 AND conname='card_events_actor_class_check') THEN
    ALTER TABLE cards.card_events ADD CONSTRAINT card_events_actor_class_check
      CHECK (actor_class IN ('human','ai_agent','search_bot','unknown'));
  END IF;
END $$;
--> statement-breakpoint
DO $$
DECLARE names text[];
BEGIN
  IF to_regclass('cards.v_funnel_daily_totals') IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected existing daily totals view; review before migrating';
  END IF;
  SELECT array_agg(attname::text ORDER BY attnum) INTO names FROM pg_attribute
    WHERE attrelid=to_regclass('cards.v_funnel_daily') AND attnum>0 AND NOT attisdropped;
  IF names=ARRAY['day','create_start','create_publish','claim_done','fact_approved','agent_fetch','share_click','view_sessions'] THEN
    -- Replay-only compatibility: preserve the old totals view and its dependents.
    -- This branch never renames the differently shaped, currently deployed view.
    ALTER VIEW cards.v_funnel_daily RENAME TO v_funnel_daily_totals;
  ELSIF names IS DISTINCT FROM ARRAY['day','event','actor_class','n'] THEN
    RAISE EXCEPTION 'Unexpected daily funnel contract; review before migrating';
  END IF;
END $$;
--> statement-breakpoint
CREATE OR REPLACE VIEW cards.v_funnel_daily_totals AS
SELECT
  (ts AT TIME ZONE 'UTC')::date AS day,
  count(*) FILTER (WHERE event='create_start') AS create_start,
  count(*) FILTER (WHERE event='create_publish') AS create_publish,
  count(*) FILTER (WHERE event='claim_done') AS claim_done,
  count(*) FILTER (WHERE event='fact_approved') AS fact_approved,
  count(*) FILTER (WHERE event='agent_fetch') AS agent_fetch,
  count(*) FILTER (WHERE event='share_click') AS share_click,
  count(DISTINCT session_hash) FILTER (WHERE event='view') AS view_sessions
FROM cards.card_events GROUP BY 1;
--> statement-breakpoint
DO $$
BEGIN
  IF to_regclass('cards.v_funnel_daily') IS NULL THEN
    CREATE VIEW cards.v_funnel_daily AS
      SELECT (date_trunc('day',ts) AT TIME ZONE 'utc')::date AS day,event,actor_class,count(*) AS n
      FROM cards.card_events GROUP BY 1,2,3;
  END IF;
END $$;
--> statement-breakpoint
-- Record the actual live search definitions. owner_email IS NOT NULL and the
-- generated claimed flag are equivalent; signatures and behavior stay intact.
CREATE OR REPLACE FUNCTION cards.match_cards(query_embedding extensions.vector, match_count integer DEFAULT 200, include_unclaimed boolean DEFAULT false)
 RETURNS TABLE(id text, handle text, card jsonb, similarity double precision)
 LANGUAGE sql STABLE SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
     and (include_unclaimed or c.owner_email is not null)
   order by c.embedding <=> query_embedding
   limit match_count;
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.search_cards_fts(q text, match_count integer DEFAULT 200, include_unclaimed boolean DEFAULT false)
 RETURNS TABLE(id text, handle text, card jsonb, rank real)
 LANGUAGE sql STABLE SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from agent_profile_cards c
   where c.status = 'published'
     and c.search_tsv @@ websearch_to_tsquery('english', q)
     and (include_unclaimed or c.owner_email is not null)
   order by 4 desc
   limit match_count;
$function$;
--> statement-breakpoint
-- Adopt the existing retention helper and its existing execute grants. This
-- migration NEVER CALLS it. The Cards schema still grants USAGE to service_role
-- only, so preserving PUBLIC execute does not expose it to browser DB roles.
CREATE OR REPLACE FUNCTION cards.purge_card_events(retention interval DEFAULT '180 days'::interval)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'cards'
AS $function$
DECLARE deleted integer;
BEGIN
  DELETE FROM cards.card_events WHERE ts < now() - retention;
  GET DIAGNOSTICS deleted = ROW_COUNT;
  RETURN deleted;
END;
$function$;
GRANT EXECUTE ON FUNCTION cards.purge_card_events(interval) TO PUBLIC,service_role;
