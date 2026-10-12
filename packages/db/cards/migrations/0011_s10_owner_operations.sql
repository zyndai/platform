-- owner: cards
-- S10 service-only transactions. Ownership uses the existing email authority.
-- Rollback: flags off; retain functions/data for backwards compatibility.

CREATE OR REPLACE FUNCTION cards.s10_merge(p_email text, p_canonical text, p_sources text[])
RETURNS jsonb LANGUAGE plpgsql SET search_path = cards, pg_temp AS $$
DECLARE c cards.agent_profile_cards%ROWTYPE; s cards.agent_profile_cards%ROWTYPE;
        source_id text; old_handles jsonb; merged integer := 0;
BEGIN
  IF cardinality(p_sources) IS NULL OR cardinality(p_sources) < 1 OR cardinality(p_sources) > 20
     OR p_canonical = ANY(p_sources) OR p_email IS NULL OR trim(p_email) = '' THEN
    RAISE EXCEPTION 'invalid merge' USING ERRCODE = '22023';
  END IF;
  -- Deterministic ordering prevents deadlocks between two merge requests.
  PERFORM id FROM cards.agent_profile_cards WHERE id = p_canonical OR id = ANY(p_sources) ORDER BY id FOR UPDATE;
  SELECT * INTO c FROM cards.agent_profile_cards WHERE id = p_canonical;
  IF NOT FOUND OR lower(c.owner_email) IS DISTINCT FROM lower(p_email) OR c.status NOT IN ('published', 'private', 'draft', 'pending_review') THEN
    RAISE EXCEPTION 'not the card owner' USING ERRCODE = '42501';
  END IF;
  old_handles := coalesce(c.card->'previous_handles', '[]'::jsonb);
  FOREACH source_id IN ARRAY p_sources LOOP
    SELECT * INTO s FROM cards.agent_profile_cards WHERE id = source_id;
    IF NOT FOUND OR lower(s.owner_email) IS DISTINCT FROM lower(p_email) THEN
      RAISE EXCEPTION 'not the card owner' USING ERRCODE = '42501';
    END IF;
    IF s.status = 'merged' AND s.merged_into = c.id THEN CONTINUE; END IF;
    IF s.status NOT IN ('published', 'private', 'draft', 'pending_review') THEN
      RAISE EXCEPTION 'card cannot be merged' USING ERRCODE = '22023';
    END IF;
    INSERT INTO cards.card_merges(owner_email, canonical_id, archived_id, snapshot)
      VALUES(lower(p_email), c.id, s.id, to_jsonb(s));
    old_handles := old_handles || jsonb_build_array(s.handle) || coalesce(s.card->'previous_handles', '[]'::jsonb);
    UPDATE cards.agent_profile_cards SET status = 'merged', merged_into = c.id,
      card = jsonb_set(card, '{status}', '"merged"'), updated_at = now() WHERE id = s.id;
    -- Flatten older redirects if their canonical card is itself merged later.
    UPDATE cards.agent_profile_cards SET merged_into = c.id WHERE merged_into = s.id;
    merged := merged + 1;
  END LOOP;
  SELECT coalesce(jsonb_agg(v), '[]'::jsonb) INTO old_handles FROM (SELECT DISTINCT v FROM jsonb_array_elements(old_handles) AS x(v) WHERE v <> 'null'::jsonb) d;
  UPDATE cards.agent_profile_cards SET card = jsonb_set(card, '{previous_handles}', old_handles), updated_at = now() WHERE id = c.id;
  RETURN jsonb_build_object('handle', c.handle, 'merged', merged);
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s10_save_section(p_email text, p_handle text, p_patch jsonb, p_expected jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path = cards, pg_temp AS $$
DECLARE r cards.agent_profile_cards%ROWTYPE; key text; next_card jsonb;
BEGIN
  SELECT * INTO r FROM cards.agent_profile_cards WHERE handle = p_handle FOR UPDATE;
  IF NOT FOUND OR lower(r.owner_email) IS DISTINCT FROM lower(p_email) OR r.status = 'merged' THEN
    RAISE EXCEPTION 'not the card owner' USING ERRCODE = '42501';
  END IF;
  IF jsonb_typeof(p_patch) <> 'object' OR jsonb_typeof(p_expected) <> 'object' THEN
    RAISE EXCEPTION 'invalid section' USING ERRCODE = '22023';
  END IF;
  FOR key IN SELECT jsonb_object_keys(p_patch) LOOP
    IF key NOT IN ('identity','summary','availability','industries','working_on','connect_with','love_talking_about','can_help_with','skills','projects','work_experience','calendly_url','google_calendar_url') OR NOT (p_expected ? key) THEN
      RAISE EXCEPTION 'invalid section' USING ERRCODE = '22023';
    END IF;
    IF r.card ? key AND r.card->key IS DISTINCT FROM p_expected->key THEN
      RAISE EXCEPTION 'section changed; reload before saving' USING ERRCODE = '40001';
    END IF;
  END LOOP;
  next_card := r.card || p_patch || jsonb_build_object('updated_at', now());
  UPDATE cards.agent_profile_cards SET card = next_card, updated_at = now(), embedding = NULL WHERE id = r.id;
  RETURN next_card || jsonb_build_object('handle', r.handle, 'status', r.status);
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s10_visibility(p_email text, p_handle text, p_public boolean)
RETURNS jsonb LANGUAGE plpgsql SET search_path = cards, pg_temp AS $$
DECLARE r cards.agent_profile_cards%ROWTYPE; next_status text;
BEGIN
  SELECT * INTO r FROM cards.agent_profile_cards WHERE handle = p_handle FOR UPDATE;
  IF NOT FOUND OR lower(r.owner_email) IS DISTINCT FROM lower(p_email) OR r.status = 'merged' THEN
    RAISE EXCEPTION 'not the card owner' USING ERRCODE = '42501';
  END IF;
  next_status := CASE WHEN p_public THEN 'published' ELSE 'private' END;
  UPDATE cards.agent_profile_cards SET status = next_status,
    card = card || jsonb_build_object('status', next_status, 'updated_at', now()), updated_at = now() WHERE id = r.id;
  RETURN jsonb_build_object('visibility', CASE WHEN p_public THEN 'public' ELSE 'private' END);
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s10_patch_system_fields(p_handle text, p_patch jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path = cards, pg_temp AS $$
DECLARE r cards.agent_profile_cards%ROWTYPE; next_card jsonb; key text;
BEGIN
  IF jsonb_typeof(p_patch) <> 'object' THEN RAISE EXCEPTION 'invalid patch' USING ERRCODE='22023'; END IF;
  FOR key IN SELECT jsonb_object_keys(p_patch) LOOP
    IF key NOT IN ('zynd_memory','work_experience','github_stats','contribution_stats','avatar_url') THEN
      RAISE EXCEPTION 'invalid system field' USING ERRCODE='22023';
    END IF;
  END LOOP;
  SELECT * INTO r FROM cards.agent_profile_cards WHERE handle=p_handle AND status <> 'merged' FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  next_card := r.card || (p_patch - 'avatar_url') || jsonb_build_object('updated_at',now());
  IF p_patch ? 'avatar_url' THEN
    next_card := jsonb_set(next_card, '{identity}', coalesce(next_card->'identity','{}'::jsonb) || jsonb_build_object('avatar_url',p_patch->'avatar_url'));
  END IF;
  UPDATE cards.agent_profile_cards SET card=next_card, updated_at=now(),
    embedding=CASE WHEN p_patch ? 'zynd_memory' THEN NULL ELSE embedding END WHERE id=r.id;
  RETURN next_card || jsonb_build_object('handle',r.handle,'status',r.status);
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION cards.s10_merge(text,text,text[]), cards.s10_save_section(text,text,jsonb,jsonb), cards.s10_visibility(text,text,boolean), cards.s10_patch_system_fields(text,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION cards.s10_merge(text,text,text[]), cards.s10_save_section(text,text,jsonb,jsonb), cards.s10_visibility(text,text,boolean), cards.s10_patch_system_fields(text,jsonb) TO service_role;
