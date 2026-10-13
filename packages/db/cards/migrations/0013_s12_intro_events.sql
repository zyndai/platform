-- owner: cards
-- Retry-safe projection and real S04 intro events in one transaction.
-- Rollback: flags off; retain additive projection and events.
GRANT ALL ON cards.intro_requests TO service_role;
REVOKE ALL ON cards.intro_requests FROM anon,authenticated;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s12_sync_intro(p_intro jsonb,p_track boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE previous cards.intro_requests; iid uuid := (p_intro->>'id')::uuid; newly_created boolean;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(iid::text,12));
  SELECT * INTO previous FROM cards.intro_requests WHERE id=iid;
  newly_created := NOT FOUND;
  INSERT INTO cards.intro_requests(id,card_id,handle,owner_uid,requester_uid,status,created_at,accepted_at)
    VALUES(iid,p_intro->>'card_id',p_intro->>'handle',(p_intro->>'owner_uid')::uuid,(p_intro->>'requester_uid')::uuid,
      p_intro->>'status',(p_intro->>'created_at')::timestamptz,
      coalesce((p_intro->>'accepted_at')::timestamptz,
        CASE WHEN p_intro->>'status' IN ('accepted','revoked') THEN (p_intro->>'decided_at')::timestamptz ELSE NULL END))
    ON CONFLICT(id) DO UPDATE SET status=CASE
      WHEN EXCLUDED.status='pending' AND cards.intro_requests.status <> 'pending' THEN cards.intro_requests.status
      WHEN EXCLUDED.status='accepted' AND cards.intro_requests.status IN ('declined','blocked','revoked') THEN cards.intro_requests.status
      ELSE EXCLUDED.status END,accepted_at=coalesce(cards.intro_requests.accepted_at,EXCLUDED.accepted_at);
  IF p_track AND newly_created THEN
    INSERT INTO cards.card_events(event,handle,actor_class,meta,ts)
      VALUES('intro_request',p_intro->>'handle','human',jsonb_build_object('intro_id',iid),(p_intro->>'created_at')::timestamptz);
  END IF;
  IF p_track AND (p_intro->>'accepted_at' IS NOT NULL OR p_intro->>'status' IN ('accepted','revoked')) AND previous.accepted_at IS NULL THEN
    INSERT INTO cards.card_events(event,handle,actor_class,meta,ts)
      VALUES('intro_accepted',p_intro->>'handle','human',jsonb_build_object('intro_id',iid),coalesce((p_intro->>'accepted_at')::timestamptz,(p_intro->>'decided_at')::timestamptz));
  END IF;
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION cards.s12_sync_intro(jsonb,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION cards.s12_sync_intro(jsonb,boolean) TO service_role;
