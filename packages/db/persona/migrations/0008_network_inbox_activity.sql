-- owner: persona
-- Backfill inbox summaries/read cursors, keep summaries current from every
-- message writer, and expose service-only inbox views to the API.
-- Rollback: drop public.dm_thread_inbox, public.persona_group_inbox,
-- dm_messages_activity_trigger, persona_group_messages_activity_trigger,
-- dm_threads_read_init_trigger, persona_group_members_read_init_trigger,
-- public.dm_message_activity(), public.persona_group_message_activity(),
-- public.dm_thread_read_init(), public.persona_group_member_read_init().

-- Read cursors are backend-only; no browser role may read another user's
-- cursor or forge one for a thread they do not participate in.
REVOKE ALL ON public.dm_thread_reads FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.persona_group_reads FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.dm_thread_reads TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.persona_group_reads TO service_role;

-- ── Backfill latest-message summaries ─────────────────────────────────
UPDATE public.dm_threads AS t
SET last_message_at = m.created_at,
    last_message_preview = left(
      btrim(regexp_replace(m.content, '[[:space:]]+', ' ', 'g')),
      140
    ),
    last_message_sender_id = m.sender_id,
    updated_at = greatest(coalesce(t.updated_at, m.created_at), m.created_at)
FROM (
  SELECT DISTINCT ON (thread_id)
    thread_id, sender_id, content, created_at
  FROM public.dm_messages
  WHERE sender_type <> 'system'
  ORDER BY thread_id, created_at DESC NULLS LAST, id DESC
) AS m
WHERE t.id = m.thread_id;

UPDATE public.persona_groups AS g
SET last_message_at = m.created_at,
    last_message_preview = left(
      btrim(regexp_replace(m.content, '[[:space:]]+', ' ', 'g')),
      140
    ),
    last_message_sender_name = m.sender_name,
    updated_at = greatest(coalesce(g.updated_at, m.created_at), m.created_at)
FROM (
  SELECT DISTINCT ON (group_id)
    group_id, sender_name, content, created_at
  FROM public.persona_group_messages
  WHERE channel <> 'system'
  ORDER BY group_id, created_at DESC NULLS LAST, id DESC
) AS m
WHERE g.id = m.group_id;

-- ── Existing conversations start read ─────────────────────────────────
-- Backfilling avoids showing years of legacy messages as unread the first
-- time an existing user opens the new inbox.
INSERT INTO public.dm_thread_reads
  (thread_id, user_id, last_read_at, created_at, updated_at)
SELECT thread_id, user_id, now(), now(), now()
FROM (
  SELECT t.id AS thread_id, p.user_id
  FROM public.dm_threads t
  JOIN public.persona_agents p
    ON p.active AND p.agent_id IN (t.initiator_id, t.receiver_id)
  UNION
  SELECT t.id, u.id
  FROM public.dm_threads t
  JOIN auth.users u
    ON u.id::text IN (t.initiator_id, t.receiver_id)
) AS participants
ON CONFLICT DO NOTHING;

INSERT INTO public.persona_group_reads
  (group_id, user_id, last_read_at, created_at, updated_at)
SELECT group_id, user_id, now(), now(), now()
FROM public.persona_group_members
ON CONFLICT DO NOTHING;

-- New threads/members start with a read cursor at creation/join time. This
-- keeps the receiver's first message unread (it arrives after the cursor)
-- while preventing a newly added group member from inheriting every old
-- message as unread.
CREATE OR REPLACE FUNCTION public.dm_thread_read_init() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  INSERT INTO public.dm_thread_reads
    (thread_id, user_id, last_read_at, created_at, updated_at)
  -- now() is transaction start; nudge the cursor back so a first message
  -- inserted in the same transaction as the thread still counts as unread.
  SELECT thread_id, user_id, now() - interval '1 microsecond', now(), now()
  FROM (
    SELECT NEW.id AS thread_id, p.user_id
    FROM public.persona_agents p
    WHERE p.active AND p.agent_id IN (NEW.initiator_id, NEW.receiver_id)
    UNION
    SELECT NEW.id, u.id
    FROM auth.users u
    WHERE u.id::text IN (NEW.initiator_id, NEW.receiver_id)
  ) AS participants
  ON CONFLICT DO NOTHING;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.dm_thread_read_init() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dm_thread_read_init() TO service_role;

CREATE OR REPLACE TRIGGER dm_threads_read_init_trigger
AFTER INSERT ON public.dm_threads
FOR EACH ROW EXECUTE FUNCTION public.dm_thread_read_init();

CREATE OR REPLACE FUNCTION public.persona_group_member_read_init() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  INSERT INTO public.persona_group_reads
    (group_id, user_id, last_read_at, created_at, updated_at)
  VALUES (
    NEW.group_id,
    NEW.user_id,
    now() - interval '1 microsecond',
    now(),
    now()
  )
  ON CONFLICT DO NOTHING;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.persona_group_member_read_init() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.persona_group_member_read_init() TO service_role;

CREATE OR REPLACE TRIGGER persona_group_members_read_init_trigger
AFTER INSERT ON public.persona_group_members
FOR EACH ROW EXECUTE FUNCTION public.persona_group_member_read_init();

-- ── Keep summaries current from every writer ──────────────────────────
-- A database trigger is deliberate: human API sends, A2A mirrors, MCP tools,
-- Telegram, and future workers all write messages through different paths.
-- Putting this in the table guarantees the inbox cannot drift from them.
CREATE OR REPLACE FUNCTION public.dm_message_activity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.sender_type = 'system' THEN
    RETURN NEW;
  END IF;
  UPDATE public.dm_threads
     SET last_message_at = NEW.created_at,
         last_message_preview = left(
           btrim(regexp_replace(NEW.content, '[[:space:]]+', ' ', 'g')),
           140
         ),
         last_message_sender_id = NEW.sender_id,
         updated_at = NEW.created_at
   WHERE id = NEW.thread_id;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.dm_message_activity() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dm_message_activity() TO service_role;

CREATE OR REPLACE TRIGGER dm_messages_activity_trigger
AFTER INSERT ON public.dm_messages
FOR EACH ROW EXECUTE FUNCTION public.dm_message_activity();

CREATE OR REPLACE FUNCTION public.persona_group_message_activity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.channel = 'system' THEN
    RETURN NEW;
  END IF;
  UPDATE public.persona_groups
     SET last_message_at = NEW.created_at,
         last_message_preview = left(
           btrim(regexp_replace(NEW.content, '[[:space:]]+', ' ', 'g')),
           140
         ),
         last_message_sender_name = NEW.sender_name,
         updated_at = NEW.created_at
   WHERE id = NEW.group_id;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.persona_group_message_activity() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.persona_group_message_activity() TO service_role;

CREATE OR REPLACE TRIGGER persona_group_messages_activity_trigger
AFTER INSERT ON public.persona_group_messages
FOR EACH ROW EXECUTE FUNCTION public.persona_group_message_activity();

-- ── Inbox views (service role only) ───────────────────────────────────
-- Unread is derived from the read cursor, so it stays correct even when a
-- message is written by an A2A/MCP/Telegram path that never touches the web
-- client. The API is the only caller; direct client roles are revoked below.
-- Owner-rights view: the migration role can read auth.users to resolve legacy
-- raw-user-id participants. Access is service-role only (grants below), so
-- this cannot be reached by a browser role.
CREATE OR REPLACE VIEW public.dm_thread_inbox
WITH (security_invoker = false)
AS
WITH participants AS (
  SELECT t.id AS thread_id, p.user_id
  FROM public.dm_threads t
  JOIN public.persona_agents p
    ON p.active AND p.agent_id IN (t.initiator_id, t.receiver_id)
  UNION
  SELECT t.id, u.id
  FROM public.dm_threads t
  JOIN auth.users u
    ON u.id::text IN (t.initiator_id, t.receiver_id)
)
SELECT
  p.user_id,
  t.id,
  t.initiator_id,
  t.receiver_id,
  t.initiator_name,
  t.receiver_name,
  t.status,
  t.lifecycle,
  t.initiator_mode,
  t.receiver_mode,
  t.last_message_at,
  t.last_message_preview,
  t.last_message_sender_id,
  t.created_at,
  t.updated_at,
  r.last_read_at,
  coalesce(t.last_message_at, t.updated_at, t.created_at) AS last_activity_at,
  (
    SELECT count(*)::integer
    FROM public.dm_messages m
    WHERE m.thread_id = t.id
      AND m.created_at > coalesce(r.last_read_at, t.created_at)
      AND m.sender_type <> 'system'
      AND m.sender_id <> p.user_id::text
      AND NOT EXISTS (
        SELECT 1
        FROM public.persona_agents own
        WHERE own.user_id = p.user_id
          AND own.active
          AND own.agent_id = m.sender_id
      )
  ) AS unread_count
FROM participants p
JOIN public.dm_threads t ON t.id = p.thread_id
LEFT JOIN public.dm_thread_reads r
  ON r.thread_id = t.id AND r.user_id = p.user_id;

REVOKE ALL ON public.dm_thread_inbox FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.dm_thread_inbox TO service_role;

CREATE OR REPLACE VIEW public.persona_group_inbox
WITH (security_invoker = false)
AS
SELECT
  mem.user_id,
  g.id,
  g.slug,
  g.name,
  g.description,
  g.avatar_url,
  g.visibility,
  g.created_at,
  g.updated_at,
  mem.role AS my_role,
  g.last_message_at,
  g.last_message_preview,
  g.last_message_sender_name,
  r.last_read_at,
  coalesce(g.last_message_at, g.updated_at, g.created_at) AS last_activity_at,
  (
    SELECT count(*)::integer
    FROM public.persona_group_messages m
    WHERE m.group_id = g.id
      AND m.created_at > coalesce(r.last_read_at, g.created_at)
      AND m.channel <> 'system'
      AND (m.sender_user_id IS NULL OR m.sender_user_id <> mem.user_id)
      AND NOT EXISTS (
        SELECT 1
        FROM public.persona_agents own
        WHERE own.user_id = mem.user_id
          AND own.active
          AND own.agent_id = m.sender_agent_id
      )
  ) AS unread_count
FROM public.persona_group_members mem
JOIN public.persona_groups g ON g.id = mem.group_id
LEFT JOIN public.persona_group_reads r
  ON r.group_id = g.id AND r.user_id = mem.user_id
WHERE g.archived_at IS NULL;

REVOKE ALL ON public.persona_group_inbox FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.persona_group_inbox TO service_role;
