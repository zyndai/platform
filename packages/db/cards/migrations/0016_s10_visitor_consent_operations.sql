-- owner: cards
-- Consent-bound named visits. Anonymous browsing is the default; turning it back
-- on hides previous names. A later opt-in never republishes old consent epochs.
-- Rollback: stop using the visitor endpoints; retain tables and service-only grants.
GRANT ALL ON cards.visitor_preferences, cards.profile_visits TO service_role;
REVOKE ALL ON cards.visitor_preferences, cards.profile_visits FROM anon,authenticated;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s10_set_visitor_privacy(p_user uuid,p_anonymous boolean,p_name text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE pref cards.visitor_preferences;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  IF p_user IS NULL OR p_anonymous IS NULL THEN RAISE EXCEPTION 'Invalid preference' USING ERRCODE='22023'; END IF;
  INSERT INTO cards.visitor_preferences(user_id,anonymous_mode,display_name)
    VALUES(p_user,p_anonymous,CASE WHEN p_anonymous THEN NULL ELSE left(p_name,80) END)
  ON CONFLICT(user_id) DO UPDATE SET anonymous_mode=EXCLUDED.anonymous_mode,
    display_name=EXCLUDED.display_name,updated_at=now(),
    consent_version=CASE WHEN visitor_preferences.anonymous_mode IS DISTINCT FROM EXCLUDED.anonymous_mode
      THEN gen_random_uuid() ELSE visitor_preferences.consent_version END
  RETURNING * INTO pref;
  RETURN jsonb_build_object('anonymous_mode',pref.anonymous_mode);
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s10_record_named_visit(p_id uuid,p_user uuid,p_email text,p_handle text,p_name text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE pref cards.visitor_preferences; target cards.agent_profile_cards;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  SELECT * INTO pref FROM cards.visitor_preferences WHERE user_id=p_user FOR UPDATE;
  IF NOT FOUND OR pref.anonymous_mode THEN RETURN false; END IF;
  SELECT * INTO target FROM cards.agent_profile_cards WHERE handle=p_handle AND status='published' AND owner_email IS NOT NULL;
  IF NOT FOUND OR lower(target.owner_email)=lower(p_email) OR target.owner_user_id=p_user THEN RETURN false; END IF;
  UPDATE cards.visitor_preferences SET display_name=left(p_name,80) WHERE user_id=p_user;
  INSERT INTO cards.profile_visits(id,card_id,visitor_id,consent_version,owner_email)
    VALUES(p_id,target.id,p_user,pref.consent_version,lower(target.owner_email)) ON CONFLICT(id) DO NOTHING;
  RETURN FOUND;
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.s10_named_visitors(p_handle text,p_owner_email text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE target cards.agent_profile_cards; result jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  SELECT * INTO target FROM cards.agent_profile_cards WHERE handle=p_handle AND lower(owner_email)=lower(p_owner_email) AND status <> 'merged';
  IF NOT FOUND THEN RAISE EXCEPTION 'Not the card owner' USING ERRCODE='42501'; END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('name',v.display_name,'visited_at',v.last_visit,'visits',v.visits) ORDER BY v.last_visit DESC),'[]'::jsonb)
    INTO result FROM (
      SELECT coalesce(nullif(trim(p.display_name),''),'Zynd member') AS display_name,max(v.visited_at) AS last_visit,count(*) AS visits
      FROM cards.profile_visits v JOIN cards.visitor_preferences p ON p.user_id=v.visitor_id
      WHERE v.card_id=target.id AND v.owner_email=lower(target.owner_email) AND NOT p.anonymous_mode
        AND p.consent_version=v.consent_version AND v.visited_at >= now()-interval '7 days'
      GROUP BY v.visitor_id,p.display_name ORDER BY max(v.visited_at) DESC LIMIT 20
    ) v;
  RETURN result;
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION cards.s10_set_visitor_privacy(uuid,boolean,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION cards.s10_record_named_visit(uuid,uuid,text,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION cards.s10_named_visitors(text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION cards.s10_set_visitor_privacy(uuid,boolean,text) TO service_role;
GRANT EXECUTE ON FUNCTION cards.s10_record_named_visit(uuid,uuid,text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION cards.s10_named_visitors(text,text) TO service_role;
