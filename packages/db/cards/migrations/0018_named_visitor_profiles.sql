-- owner: cards
-- Add a public profile handle to consenting visitors, resolved by account ID.
-- Keep owner checks, consent epochs, retention window and existing function grants.
-- Visitors without a published UID-owned card keep a null handle; never guess by name.
-- Rollback SQL (restore the previous response shape):
-- CREATE OR REPLACE FUNCTION cards.s10_named_visitors(p_handle text,p_owner_email text)
-- RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
-- DECLARE target cards.agent_profile_cards; result jsonb;
-- BEGIN
--   IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
--   SELECT * INTO target FROM cards.agent_profile_cards WHERE handle=p_handle AND lower(owner_email)=lower(p_owner_email) AND status <> 'merged';
--   IF NOT FOUND THEN RAISE EXCEPTION 'Not the card owner' USING ERRCODE='42501'; END IF;
--   SELECT coalesce(jsonb_agg(jsonb_build_object('name',v.display_name,'visited_at',v.last_visit,'visits',v.visits) ORDER BY v.last_visit DESC),'[]'::jsonb)
--     INTO result FROM (
--       SELECT coalesce(nullif(trim(p.display_name),''),'Zynd member') AS display_name,max(v.visited_at) AS last_visit,count(*) AS visits
--       FROM cards.profile_visits v JOIN cards.visitor_preferences p ON p.user_id=v.visitor_id
--       WHERE v.card_id=target.id AND v.owner_email=lower(target.owner_email) AND NOT p.anonymous_mode
--         AND p.consent_version=v.consent_version AND v.visited_at >= now()-interval '7 days'
--       GROUP BY v.visitor_id,p.display_name ORDER BY max(v.visited_at) DESC LIMIT 20
--     ) v;
--   RETURN result;
-- END $$;

CREATE OR REPLACE FUNCTION cards.s10_named_visitors(p_handle text,p_owner_email text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE target cards.agent_profile_cards; result jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  SELECT * INTO target FROM cards.agent_profile_cards WHERE handle=p_handle AND lower(owner_email)=lower(p_owner_email) AND status <> 'merged';
  IF NOT FOUND THEN RAISE EXCEPTION 'Not the card owner' USING ERRCODE='42501'; END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
    'name',v.display_name,'visited_at',v.last_visit,'visits',v.visits,'handle',profile.handle
  ) ORDER BY v.last_visit DESC),'[]'::jsonb)
    INTO result FROM (
      SELECT v.visitor_id,coalesce(nullif(trim(p.display_name),''),'Zynd member') AS display_name,
        max(v.visited_at) AS last_visit,count(*) AS visits
      FROM cards.profile_visits v JOIN cards.visitor_preferences p ON p.user_id=v.visitor_id
      WHERE v.card_id=target.id AND v.owner_email=lower(target.owner_email) AND NOT p.anonymous_mode
        AND p.consent_version=v.consent_version AND v.visited_at >= now()-interval '7 days'
      GROUP BY v.visitor_id,p.display_name ORDER BY max(v.visited_at) DESC LIMIT 20
    ) v
    LEFT JOIN LATERAL (
      SELECT c.handle FROM cards.agent_profile_cards c
      WHERE c.owner_user_id=v.visitor_id AND c.status='published' AND nullif(trim(c.handle),'') IS NOT NULL
      ORDER BY c.published_at DESC NULLS LAST,c.id LIMIT 1
    ) profile ON true;
  RETURN result;
END $$;
