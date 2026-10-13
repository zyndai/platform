-- owner: persona
-- Atomic human intro intake/decisions and protection against direct-client escalation.
-- Rollback: disable FEATURE_S12_INTROS. Keep audits/functions and the security
-- trigger; removing it reintroduces the permission escalation found in the audit.

GRANT SELECT ON public.persona_intro_requests TO authenticated;
GRANT ALL ON public.persona_intro_requests, public.persona_intro_rules, public.persona_intro_audit TO service_role;
REVOKE INSERT, UPDATE, DELETE ON public.persona_intro_requests, public.persona_intro_rules, public.persona_intro_audit FROM anon, authenticated;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_guard_thread_write() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF auth.role() IN ('anon', 'authenticated') THEN
    IF TG_OP = 'INSERT' THEN
      IF NEW.status <> 'pending' OR NEW.permissions IS DISTINCT FROM
        jsonb_build_object('can_request_meetings', true, 'can_query_availability', false,
                          'can_view_full_profile', false, 'can_post_on_my_behalf', false) THEN
        RAISE EXCEPTION 'Connection grants require the owner API' USING ERRCODE = '42501';
      END IF;
    ELSIF NEW.status IS DISTINCT FROM OLD.status OR NEW.permissions IS DISTINCT FROM OLD.permissions
       OR NEW.initiator_id IS DISTINCT FROM OLD.initiator_id OR NEW.receiver_id IS DISTINCT FROM OLD.receiver_id THEN
      RAISE EXCEPTION 'Connection decisions require the owner API' USING ERRCODE = '42501';
    END IF;
  END IF;
  RETURN NEW;
END $$;
--> statement-breakpoint
CREATE OR REPLACE TRIGGER s12_thread_write_guard BEFORE INSERT OR UPDATE ON public.dm_threads
FOR EACH ROW EXECUTE FUNCTION public.s12_guard_thread_write();
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_create_intro(
  p_card_id text, p_handle text, p_requester_uid uuid, p_owner_uid uuid,
  p_why text, p_asks jsonb, p_key uuid, p_requester_cap integer, p_card_cap integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r public.persona_intro_requests; sender public.persona_agents; recipient public.persona_agents;
  tid uuid; decision_rule text; snapshot jsonb := '{"can_request_meetings":false,"can_query_availability":false,"can_view_full_profile":false,"can_post_on_my_behalf":false}'::jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  IF p_requester_uid IS NULL OR p_owner_uid IS NULL OR p_key IS NULL OR p_card_id IS NULL OR p_handle IS NULL OR p_why IS NULL
    OR p_requester_uid = p_owner_uid OR length(trim(p_why)) NOT BETWEEN 10 AND 2000
    OR p_asks IS NULL OR jsonb_typeof(p_asks) <> 'array' OR jsonb_array_length(p_asks) NOT BETWEEN 1 AND 2
    OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_asks) a WHERE a NOT IN ('message','meeting'))
    OR p_requester_cap < 1 OR p_card_cap < 1 THEN
    RAISE EXCEPTION 'Invalid intro' USING ERRCODE='22023';
  END IF;
  -- Consistent lock order makes limits and duplicate submissions safe across workers.
  PERFORM pg_advisory_xact_lock(hashtextextended(least(p_requester_uid::text,p_owner_uid::text), 12));
  PERFORM pg_advisory_xact_lock(hashtextextended(greatest(p_requester_uid::text,p_owner_uid::text), 12));
  SELECT * INTO r FROM public.persona_intro_requests WHERE requester_uid=p_requester_uid AND idempotency_key=p_key;
  IF FOUND THEN
    IF r.card_id <> p_card_id OR r.owner_uid <> p_owner_uid OR r.why <> p_why OR r.asks <> p_asks THEN
      RETURN jsonb_build_object('error','idempotency_conflict');
    END IF;
    RETURN to_jsonb(r);
  END IF;
  SELECT * INTO sender FROM public.persona_agents WHERE user_id=p_requester_uid AND active LIMIT 1;
  SELECT * INTO recipient FROM public.persona_agents WHERE user_id=p_owner_uid AND active LIMIT 1;
  IF sender.agent_id IS NULL OR recipient.agent_id IS NULL THEN RETURN jsonb_build_object('error','persona_required'); END IF;
  SELECT t.rule INTO decision_rule FROM public.persona_intro_rules t WHERE owner_uid=p_owner_uid AND requester_uid=p_requester_uid;
  IF decision_rule='deny' OR (decision_rule IS DISTINCT FROM 'allow' AND EXISTS
    (SELECT 1 FROM public.persona_intro_rules t WHERE t.owner_uid=p_owner_uid AND t.rule='allow')) THEN
    INSERT INTO public.persona_intro_audit(actor_uid,owner_uid,action,details) VALUES(p_requester_uid,p_owner_uid,'denied',jsonb_build_object('card_id',p_card_id));
    RETURN jsonb_build_object('error','denied');
  END IF;
  IF (SELECT count(*) FROM public.persona_intro_requests WHERE requester_uid=p_requester_uid
      AND created_at >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') >= p_requester_cap
    OR (SELECT count(*) FROM public.persona_intro_requests WHERE card_id=p_card_id
      AND created_at >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') >= p_card_cap THEN
    INSERT INTO public.persona_intro_audit(actor_uid,owner_uid,action,details) VALUES(p_requester_uid,p_owner_uid,'rate_limited',jsonb_build_object('card_id',p_card_id));
    RETURN jsonb_build_object('error','rate_limited');
  END IF;
  IF EXISTS (SELECT 1 FROM public.dm_threads WHERE
    (initiator_id=sender.agent_id AND receiver_id=recipient.agent_id) OR
    (initiator_id=recipient.agent_id AND receiver_id=sender.agent_id)) THEN
    RETURN jsonb_build_object('error','connection_exists');
  END IF;
  INSERT INTO public.dm_threads(initiator_id,receiver_id,initiator_name,receiver_name,permissions,initiator_mode,receiver_mode)
    VALUES(sender.agent_id,recipient.agent_id,sender.name,recipient.name,snapshot,'human','human') RETURNING id INTO tid;
  INSERT INTO public.persona_intro_requests(card_id,handle,requester_uid,owner_uid,requester_agent_id,owner_agent_id,
    requester_name,owner_name,why,asks,permissions,idempotency_key,thread_id)
    VALUES(p_card_id,p_handle,p_requester_uid,p_owner_uid,sender.agent_id,recipient.agent_id,
      sender.name,recipient.name,p_why,p_asks,snapshot,p_key,tid) RETURNING * INTO r;
  INSERT INTO public.dm_messages(thread_id,sender_id,sender_type,channel,content)
    VALUES(tid,p_requester_uid::text,'human','human',p_why);
  INSERT INTO public.persona_intro_audit(intro_id,actor_uid,owner_uid,action) VALUES(r.id,p_requester_uid,p_owner_uid,'requested');
  RETURN to_jsonb(r);
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_respond_intro(p_id uuid,p_actor uuid,p_action text,p_allow_meetings boolean,
  p_start timestamptz DEFAULT NULL,p_end timestamptz DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE r public.persona_intro_requests; task_id uuid; snapshot jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  SELECT * INTO r FROM public.persona_intro_requests WHERE id=p_id FOR UPDATE;
  IF p_actor IS NULL OR NOT FOUND OR (r.owner_uid <> p_actor AND NOT (p_action='revoke' AND r.requester_uid=p_actor)) THEN
    RAISE EXCEPTION 'Not the receiving owner' USING ERRCODE='42501'; END IF;
  IF p_action NOT IN ('accept','decline','block','propose_time','revoke') THEN RAISE EXCEPTION 'Invalid decision' USING ERRCODE='22023'; END IF;
  IF p_action='revoke' THEN
    IF r.status NOT IN ('accepted','revoked') THEN RAISE EXCEPTION 'Intro not accepted' USING ERRCODE='40001'; END IF;
    IF r.status='revoked' THEN RETURN to_jsonb(r); END IF;
    UPDATE public.persona_intro_requests SET status='revoked' WHERE id=r.id RETURNING * INTO r;
    UPDATE public.dm_threads SET status='revoked',updated_at=now() WHERE id=r.thread_id;
    UPDATE public.a2a_tasks SET state='canceled',failure_reason='connection_revoked',terminal_at=now()
      WHERE context_id=r.thread_id AND state IN ('submitted','working','input-required','auth-required');
    INSERT INTO public.persona_intro_audit(intro_id,actor_uid,owner_uid,action) VALUES(r.id,p_actor,r.owner_uid,'revoked');
    RETURN to_jsonb(r);
  END IF;
  IF (p_start IS NULL) <> (p_end IS NULL) OR (p_start IS NOT NULL AND (p_start <= now() OR p_end <= p_start OR p_end-p_start > interval '2 hours')) THEN
    RAISE EXCEPTION 'Invalid meeting time' USING ERRCODE='22023';
  END IF;
  IF p_action='propose_time' THEN
    IF r.status <> 'accepted' OR NOT coalesce((r.permissions->>'can_request_meetings')::boolean,false) OR p_start IS NULL THEN
      RAISE EXCEPTION 'Meeting not granted' USING ERRCODE='42501';
    END IF;
    PERFORM 1 FROM public.dm_threads WHERE id=r.thread_id AND status='accepted'
      AND coalesce((permissions->>'can_request_meetings')::boolean,false) FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Meeting permission revoked' USING ERRCODE='42501'; END IF;
    IF r.meeting_task_id IS NOT NULL THEN RETURN to_jsonb(r); END IF;
  ELSE
    IF r.status <> 'pending' AND NOT (p_action='block' AND r.status='accepted') THEN
      IF r.status=(CASE p_action WHEN 'accept' THEN 'accepted' WHEN 'decline' THEN 'declined' ELSE 'blocked' END) THEN RETURN to_jsonb(r); END IF;
      RAISE EXCEPTION 'Intro already decided' USING ERRCODE='40001';
    END IF;
    IF p_allow_meetings AND NOT (r.asks ? 'meeting') THEN RAISE EXCEPTION 'Meeting not requested' USING ERRCODE='22023'; END IF;
    snapshot := jsonb_build_object('can_request_meetings',p_action='accept' AND p_allow_meetings,
      'can_query_availability',false,'can_view_full_profile',false,'can_post_on_my_behalf',false);
    IF p_start IS NOT NULL AND NOT (snapshot->>'can_request_meetings')::boolean THEN RAISE EXCEPTION 'Meeting not granted' USING ERRCODE='42501'; END IF;
    UPDATE public.persona_intro_requests SET status=CASE p_action WHEN 'accept' THEN 'accepted' WHEN 'decline' THEN 'declined' ELSE 'blocked' END,
      permissions=snapshot,decided_at=now() WHERE id=r.id RETURNING * INTO r;
    UPDATE public.dm_threads SET status=r.status,permissions=r.permissions,updated_at=now() WHERE id=r.thread_id;
    IF r.status IN ('declined','blocked') THEN
      UPDATE public.a2a_tasks SET state='canceled',failure_reason='connection_'||r.status,terminal_at=now()
        WHERE context_id=r.thread_id AND state IN ('submitted','working','input-required','auth-required');
    END IF;
    IF r.status='blocked' THEN
      INSERT INTO public.persona_intro_rules(owner_uid,requester_uid,rule) VALUES(r.owner_uid,r.requester_uid,'deny')
      ON CONFLICT(owner_uid,requester_uid) DO UPDATE SET rule='deny';
    END IF;
    INSERT INTO public.persona_intro_audit(intro_id,actor_uid,owner_uid,action) VALUES(r.id,p_actor,r.owner_uid,r.status);
  END IF;
  IF p_start IS NOT NULL THEN
    INSERT INTO public.agent_tasks(thread_id,type,status,initiator_user_id,recipient_user_id,initiator_agent_id,recipient_agent_id,payload,history)
      VALUES(r.thread_id,'meeting','proposed',r.owner_uid,r.requester_uid,r.owner_agent_id,r.requester_agent_id,
        jsonb_build_object('title','Zynd introduction','start_time',p_start,'end_time',p_end,'description','Introduction requested via Zynd Cards'),
        jsonb_build_array(jsonb_build_object('at',now(),'actor_user_id',p_actor,'action','proposed')))
      RETURNING id INTO task_id;
    UPDATE public.persona_intro_requests SET meeting_task_id=task_id WHERE id=r.id RETURNING * INTO r;
    INSERT INTO public.persona_intro_audit(intro_id,actor_uid,owner_uid,action) VALUES(r.id,p_actor,r.owner_uid,'meeting_proposed');
  END IF;
  RETURN to_jsonb(r);
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION public.s12_create_intro(text,text,uuid,uuid,text,jsonb,uuid,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.s12_respond_intro(uuid,uuid,text,boolean,timestamptz,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.s12_create_intro(text,text,uuid,uuid,text,jsonb,uuid,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.s12_respond_intro(uuid,uuid,text,boolean,timestamptz,timestamptz) TO service_role;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_guard_pending_message() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
  IF auth.role() IN ('anon','authenticated') AND EXISTS (
    SELECT 1 FROM public.persona_intro_requests i JOIN public.dm_threads t ON t.id=i.thread_id
    WHERE i.thread_id=NEW.thread_id AND (i.status <> 'accepted' OR t.status <> 'accepted')) THEN
    RAISE EXCEPTION 'Intro is awaiting owner approval' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
--> statement-breakpoint
CREATE OR REPLACE TRIGGER s12_pending_message_guard BEFORE INSERT ON public.dm_messages
FOR EACH ROW EXECUTE FUNCTION public.s12_guard_pending_message();
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_guard_meeting_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
  IF auth.role() IN ('anon','authenticated') THEN
    RAISE EXCEPTION 'Meeting decisions require the owner API' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
--> statement-breakpoint
CREATE OR REPLACE TRIGGER s12_meeting_write_guard BEFORE INSERT OR UPDATE ON public.agent_tasks
FOR EACH ROW EXECUTE FUNCTION public.s12_guard_meeting_write();
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_set_intro_rule(p_owner uuid,p_requester uuid,p_rule text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(p_owner::text,12));
  IF p_rule IS NULL THEN
    DELETE FROM public.persona_intro_rules WHERE owner_uid=p_owner AND requester_uid=p_requester;
  ELSIF p_rule IN ('allow','deny') THEN
    INSERT INTO public.persona_intro_rules(owner_uid,requester_uid,rule) VALUES(p_owner,p_requester,p_rule)
      ON CONFLICT(owner_uid,requester_uid) DO UPDATE SET rule=p_rule;
  ELSE RAISE EXCEPTION 'Invalid intro rule' USING ERRCODE='22023'; END IF;
  INSERT INTO public.persona_intro_audit(actor_uid,owner_uid,action,details)
    VALUES(p_owner,p_owner,'rule_changed',jsonb_build_object('requester_uid',p_requester,'rule',p_rule));
  RETURN jsonb_build_object('ok',true);
END $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.s12_save_thread_permissions(p_thread uuid,p_actor uuid,p_patch jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE t public.dm_threads; i public.persona_intro_requests; merged jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN RAISE EXCEPTION 'Service only' USING ERRCODE='42501'; END IF;
  -- Lock the intro before its thread, matching decision/proposal lock order.
  SELECT * INTO i FROM public.persona_intro_requests WHERE thread_id=p_thread FOR UPDATE;
  SELECT * INTO t FROM public.dm_threads WHERE id=p_thread FOR UPDATE;
  IF p_actor IS NULL OR NOT FOUND OR NOT (t.receiver_id=p_actor::text OR EXISTS
    (SELECT 1 FROM public.persona_agents WHERE user_id=p_actor AND agent_id=t.receiver_id)) THEN
    RAISE EXCEPTION 'Not the receiving owner' USING ERRCODE='42501';
  END IF;
  IF p_patch IS NULL OR jsonb_typeof(p_patch) <> 'object' OR p_patch='{}'::jsonb OR EXISTS
    (SELECT 1 FROM jsonb_each(p_patch) item WHERE item.key NOT IN
      ('can_request_meetings','can_query_availability','can_view_full_profile','can_post_on_my_behalf')
      OR jsonb_typeof(item.value) <> 'boolean') THEN RAISE EXCEPTION 'Invalid permission' USING ERRCODE='22023'; END IF;
  IF i.id IS NOT NULL AND EXISTS (SELECT 1 FROM jsonb_each(p_patch) item
    WHERE item.value='true'::jsonb AND NOT coalesce((i.permissions->>item.key)::boolean,false)) THEN
    RAISE EXCEPTION 'Permission not granted for this intro' USING ERRCODE='42501'; END IF;
  merged := t.permissions || p_patch;
  UPDATE public.dm_threads SET permissions=merged,updated_at=now() WHERE id=p_thread;
  IF i.id IS NOT NULL THEN
    INSERT INTO public.persona_intro_audit(intro_id,actor_uid,owner_uid,action,details)
      VALUES(i.id,p_actor,p_actor,'permissions_changed',p_patch);
  END IF;
  RETURN jsonb_build_object('thread_id',p_thread,'permissions',merged,'status','ok');
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION public.s12_set_intro_rule(uuid,uuid,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.s12_save_thread_permissions(uuid,uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.s12_set_intro_rule(uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.s12_save_thread_permissions(uuid,uuid,jsonb) TO service_role;
