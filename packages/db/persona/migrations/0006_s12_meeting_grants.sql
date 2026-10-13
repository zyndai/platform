-- owner: persona
-- Preserve an intro's current meeting grant when responding to an existing ticket.
-- Rollback: disable S12; retain the guard against booking after permission revocation.
CREATE OR REPLACE FUNCTION public.s12_guard_meeting_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE intro public.persona_intro_requests; thread public.dm_threads;
BEGIN
  IF auth.role() IN ('anon','authenticated') THEN
    RAISE EXCEPTION 'Meeting decisions require the owner API' USING ERRCODE='42501';
  END IF;
  IF NEW.status IN ('proposed','countered','accepted') THEN
    SELECT * INTO intro FROM public.persona_intro_requests WHERE thread_id=NEW.thread_id FOR UPDATE;
    IF FOUND THEN
      SELECT * INTO thread FROM public.dm_threads WHERE id=NEW.thread_id FOR UPDATE;
      IF intro.status <> 'accepted' OR thread.status <> 'accepted'
        OR NOT coalesce((thread.permissions->>'can_request_meetings')::boolean,false) THEN
        RAISE EXCEPTION 'Intro meeting permission revoked' USING ERRCODE='42501';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
