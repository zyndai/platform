-- owner: cards
-- Cards network messaging v2: per-conversation sequence, idempotent sends,
-- inbox summaries, read cursors, and Realtime Broadcast triggers.
--
-- Expand-only. Existing messages are backfilled before NOT NULL/unique
-- constraints are added. Existing conversations start fully read so the new
-- unread UI does not surface years of history.
--
-- Rollback: drop the Realtime policy and authorization function, the message
-- triggers/functions, the read-state tables, the added indexes/constraints,
-- and the added columns. Message rows themselves are never dropped.

-- ── Add nullable columns first so existing rows can be backfilled ─────
ALTER TABLE "cards"."dm_messages" ADD COLUMN "seq" bigint;--> statement-breakpoint
ALTER TABLE "cards"."dm_messages" ADD COLUMN "client_id" uuid;--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD COLUMN "message_count" bigint DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD COLUMN "last_message_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD COLUMN "last_message_preview" text;--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD COLUMN "last_message_sender_user_id" uuid;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD COLUMN "seq" bigint;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD COLUMN "client_id" uuid;--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD COLUMN "message_count" bigint DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD COLUMN "last_message_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD COLUMN "last_message_preview" text;--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD COLUMN "last_message_sender_user_id" uuid;--> statement-breakpoint

-- ── Backfill the per-conversation sequence in insert order ────────────
WITH numbered AS (
  SELECT id, row_number() OVER (PARTITION BY thread_id ORDER BY created_at, id) AS seq
  FROM "cards"."dm_messages"
)
UPDATE "cards"."dm_messages" m SET seq = n.seq
FROM numbered n WHERE m.id = n.id;--> statement-breakpoint
WITH numbered AS (
  SELECT id, row_number() OVER (PARTITION BY group_id ORDER BY created_at, id) AS seq
  FROM "cards"."group_messages"
)
UPDATE "cards"."group_messages" m SET seq = n.seq
FROM numbered n WHERE m.id = n.id;--> statement-breakpoint
ALTER TABLE "cards"."dm_messages" ALTER COLUMN "seq" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ALTER COLUMN "seq" SET NOT NULL;--> statement-breakpoint

-- ── Backfill message counts and last-message summaries ────────────────
UPDATE "cards"."dm_threads" t
SET message_count = coalesce(m.max_seq, 0)
FROM (
  SELECT thread_id, max(seq) AS max_seq
  FROM "cards"."dm_messages" GROUP BY thread_id
) m
WHERE t.id = m.thread_id;--> statement-breakpoint
UPDATE "cards"."dm_threads" t
SET last_message_at = m.created_at,
    last_message_preview = left(btrim(regexp_replace(m.content, '[[:space:]]+', ' ', 'g')), 140),
    last_message_sender_user_id = m.sender_user_id,
    updated_at = greatest(t.updated_at, m.created_at)
FROM (
  SELECT DISTINCT ON (thread_id)
    thread_id, sender_user_id, content, created_at
  FROM "cards"."dm_messages"
  ORDER BY thread_id, seq DESC
) m
WHERE t.id = m.thread_id;--> statement-breakpoint
UPDATE "cards"."groups" g
SET message_count = coalesce(m.max_seq, 0)
FROM (
  SELECT group_id, max(seq) AS max_seq
  FROM "cards"."group_messages" GROUP BY group_id
) m
WHERE g.id = m.group_id;--> statement-breakpoint
UPDATE "cards"."groups" g
SET last_message_at = m.created_at,
    last_message_preview = left(btrim(regexp_replace(m.content, '[[:space:]]+', ' ', 'g')), 140),
    last_message_sender_user_id = m.sender_user_id,
    updated_at = greatest(g.updated_at, m.created_at)
FROM (
  SELECT DISTINCT ON (group_id)
    group_id, sender_user_id, content, created_at
  FROM "cards"."group_messages"
  ORDER BY group_id, seq DESC
) m
WHERE g.id = m.group_id;--> statement-breakpoint

-- ── Per-user read cursors ─────────────────────────────────────────────
CREATE TABLE "cards"."dm_read_state" (
	"thread_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"last_read_seq" bigint DEFAULT 0 NOT NULL,
	"last_read_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_dm_read_state_pkey" PRIMARY KEY("thread_id","user_id"),
	CONSTRAINT "cards_dm_read_state_seq_check" CHECK (last_read_seq >= 0)
);--> statement-breakpoint
ALTER TABLE "cards"."dm_read_state" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_read_state" (
	"group_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"last_read_seq" bigint DEFAULT 0 NOT NULL,
	"last_read_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_group_read_state_pkey" PRIMARY KEY("group_id","user_id"),
	CONSTRAINT "cards_group_read_state_seq_check" CHECK (last_read_seq >= 0)
);--> statement-breakpoint
ALTER TABLE "cards"."group_read_state" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."dm_read_state" ADD CONSTRAINT "cards_dm_read_state_thread_fkey" FOREIGN KEY ("thread_id") REFERENCES "cards"."dm_threads"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."dm_read_state" ADD CONSTRAINT "cards_dm_read_state_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_read_state" ADD CONSTRAINT "cards_group_read_state_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_read_state" ADD CONSTRAINT "cards_group_read_state_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "cards_dm_read_state_user_idx" ON "cards"."dm_read_state" USING btree ("user_id","last_read_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "cards_group_read_state_user_idx" ON "cards"."group_read_state" USING btree ("user_id","last_read_at" DESC NULLS LAST);--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD CONSTRAINT "cards_dm_threads_last_sender_fkey" FOREIGN KEY ("last_message_sender_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD CONSTRAINT "cards_groups_last_sender_fkey" FOREIGN KEY ("last_message_sender_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "cards_dm_messages_thread_seq_key" ON "cards"."dm_messages" USING btree ("thread_id","seq");--> statement-breakpoint
CREATE UNIQUE INDEX "cards_dm_messages_client_key" ON "cards"."dm_messages" USING btree ("thread_id","sender_user_id","client_id") WHERE client_id IS NOT NULL;--> statement-breakpoint
CREATE INDEX "cards_dm_threads_last_message_idx" ON "cards"."dm_threads" USING btree ("last_message_at" DESC NULLS LAST);--> statement-breakpoint
CREATE UNIQUE INDEX "cards_group_messages_group_seq_key" ON "cards"."group_messages" USING btree ("group_id","seq");--> statement-breakpoint
CREATE UNIQUE INDEX "cards_group_messages_client_key" ON "cards"."group_messages" USING btree ("group_id","sender_user_id","client_id") WHERE client_id IS NOT NULL;--> statement-breakpoint
CREATE INDEX "cards_groups_last_message_idx" ON "cards"."groups" USING btree ("last_message_at" DESC NULLS LAST);--> statement-breakpoint
ALTER TABLE "cards"."dm_messages" ADD CONSTRAINT "cards_dm_messages_seq_check" CHECK (seq > 0);--> statement-breakpoint
ALTER TABLE "cards"."dm_threads" ADD CONSTRAINT "cards_dm_threads_message_count_check" CHECK (message_count >= 0);--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_seq_check" CHECK (seq > 0);--> statement-breakpoint
ALTER TABLE "cards"."groups" ADD CONSTRAINT "cards_groups_message_count_check" CHECK (message_count >= 0);--> statement-breakpoint
CREATE POLICY "service role full access on dm_read_state" ON "cards"."dm_read_state" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_read_state" ON "cards"."group_read_state" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint

-- Existing conversations start read. New threads/members are initialized by
-- triggers below; new members of an existing group start at the current count
-- so they do not inherit old history as unread.
INSERT INTO "cards"."dm_read_state" ("thread_id","user_id","last_read_seq","last_read_at")
SELECT t.id, p.user_id, t.message_count, now()
FROM "cards"."dm_threads" t
JOIN "cards"."connections" c ON c.id = t.connection_id
CROSS JOIN LATERAL (VALUES (c.requester_user_id), (c.recipient_user_id)) AS p(user_id)
ON CONFLICT DO NOTHING;--> statement-breakpoint
INSERT INTO "cards"."group_read_state" ("group_id","user_id","last_read_seq","last_read_at")
SELECT g.id, m.user_id, g.message_count, now()
FROM "cards"."groups" g
JOIN "cards"."group_members" m ON m.group_id = g.id
ON CONFLICT DO NOTHING;--> statement-breakpoint

-- ── Card payload helper (one SQL statement, no per-row HTTP) ──────────
CREATE OR REPLACE FUNCTION "cards"."network_card_payload"(p_card_id text)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = cards, pg_temp AS $$
  SELECT jsonb_build_object(
    'card_id', c.id,
    'handle', c.handle,
    'name', coalesce(c.card->'identity'->>'name', 'Zynd member'),
    'headline', coalesce(c.card->'identity'->>'headline', ''),
    'avatar_url', coalesce(c.card->'identity'->>'avatar_url', c.card->'profile'->>'avatar_url')
  )
  FROM "cards"."agent_profile_cards" c
  WHERE c.id = p_card_id
$$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_card_payload"(text) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_card_payload"(text) TO service_role;--> statement-breakpoint

-- ── Inbox: connections, groups, invitations, summaries, unread ────────
CREATE OR REPLACE FUNCTION "cards"."network_inbox"(p_user uuid)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_connections jsonb;
  v_groups jsonb;
  v_invitations jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;

  SELECT coalesce(jsonb_agg(item ORDER BY sort_at DESC), '[]'::jsonb) INTO v_connections
  FROM (
    SELECT jsonb_build_object(
      'id', c.id,
      'status', c.status,
      'incoming', c.recipient_user_id = p_user,
      'created_at', c.created_at,
      'decided_at', c.decided_at,
      'updated_at', c.updated_at,
      'request_message', c.request_message,
      'partner', "cards"."network_card_payload"(
        CASE WHEN c.requester_user_id = p_user THEN c.recipient_card_id ELSE c.requester_card_id END
      ),
      'thread_id', t.id,
      'last_message_at', t.last_message_at,
      'last_message_preview', t.last_message_preview,
      'last_message_sender_user_id', t.last_message_sender_user_id,
      'unread_count', CASE
        WHEN c.status = 'accepted'
          THEN greatest(coalesce(t.message_count, 0) - coalesce(r.last_read_seq, 0), 0)
        ELSE 0
      END
    ) AS item,
    coalesce(t.last_message_at, c.updated_at, c.created_at) AS sort_at
    FROM "cards"."connections" c
    LEFT JOIN "cards"."dm_threads" t ON t.connection_id = c.id
    LEFT JOIN "cards"."dm_read_state" r ON r.thread_id = t.id AND r.user_id = p_user
    WHERE c.requester_user_id = p_user OR c.recipient_user_id = p_user
  ) s;

  SELECT coalesce(jsonb_agg(item ORDER BY sort_at DESC), '[]'::jsonb) INTO v_groups
  FROM (
    SELECT jsonb_build_object(
      'id', g.id,
      'name', g.name,
      'description', g.description,
      'owner_user_id', g.owner_user_id,
      'visibility', g.visibility,
      'my_role', m.role,
      'created_at', g.created_at,
      'updated_at', g.updated_at,
      'last_message_at', g.last_message_at,
      'last_message_preview', g.last_message_preview,
      'last_message_sender_user_id', g.last_message_sender_user_id,
      'unread_count', greatest(coalesce(g.message_count, 0) - coalesce(r.last_read_seq, 0), 0)
    ) AS item,
    coalesce(g.last_message_at, g.updated_at, g.created_at) AS sort_at
    FROM "cards"."group_members" m
    JOIN "cards"."groups" g ON g.id = m.group_id
    LEFT JOIN "cards"."group_read_state" r ON r.group_id = g.id AND r.user_id = p_user
    WHERE m.user_id = p_user AND g.archived_at IS NULL
  ) s;

  SELECT coalesce(jsonb_agg(jsonb_build_object(
      'id', i.id,
      'group_id', i.group_id,
      'invitee_user_id', i.invitee_user_id,
      'inviter_user_id', i.inviter_user_id,
      'status', i.status,
      'message', i.message,
      'created_at', i.created_at,
      'expires_at', i.expires_at,
      'group', jsonb_build_object('id', g.id, 'name', g.name, 'description', g.description)
    ) ORDER BY i.created_at DESC), '[]'::jsonb) INTO v_invitations
  FROM "cards"."group_invitations" i
  JOIN "cards"."groups" g ON g.id = i.group_id AND g.archived_at IS NULL
  WHERE i.invitee_user_id = p_user
    AND i.status = 'pending'
    AND i.expires_at > now();

  RETURN jsonb_build_object(
    'connections', v_connections,
    'groups', v_groups,
    'invitations', v_invitations,
    'server_time', now()
  );
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_inbox"(uuid) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_inbox"(uuid) TO service_role;--> statement-breakpoint

-- ── DM message page (before_seq / after_seq cursor) ───────────────────
CREATE OR REPLACE FUNCTION "cards"."network_dm_messages"(
  p_user uuid, p_connection uuid,
  p_before_seq bigint DEFAULT NULL, p_after_seq bigint DEFAULT NULL,
  p_limit integer DEFAULT 50
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_thread uuid;
  v_limit integer;
  v_messages jsonb;
  v_has_more boolean;
  v_latest bigint;
  v_peer_read bigint;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."connections" c
    WHERE c.id = p_connection AND c.status = 'accepted'
      AND p_user IN (c.requester_user_id, c.recipient_user_id)
  ) THEN
    RETURN jsonb_build_object('error', 'Connection not found', 'status_code', 404);
  END IF;

  SELECT id INTO v_thread FROM "cards"."dm_threads" WHERE connection_id = p_connection;
  IF v_thread IS NULL THEN
    INSERT INTO "cards"."dm_threads" (connection_id) VALUES (p_connection)
    ON CONFLICT (connection_id) DO UPDATE SET connection_id = EXCLUDED.connection_id
    RETURNING id INTO v_thread;
  END IF;

  SELECT coalesce(max(last_read_seq), 0) INTO v_peer_read
  FROM "cards"."dm_read_state"
  WHERE thread_id = v_thread AND user_id <> p_user;

  v_limit := greatest(1, least(coalesce(p_limit, 50), 500));

  WITH page AS (
    SELECT id, thread_id, seq, client_id, sender_user_id, content, created_at
    FROM "cards"."dm_messages"
    WHERE thread_id = v_thread
      AND (p_before_seq IS NULL OR seq < p_before_seq)
      AND (p_after_seq IS NULL OR seq > p_after_seq)
    ORDER BY seq DESC
    LIMIT v_limit + 1
  ), trimmed AS (
    SELECT * FROM page ORDER BY seq DESC LIMIT v_limit
  )
  SELECT coalesce(jsonb_agg(to_jsonb(trimmed) ORDER BY seq), '[]'::jsonb),
         (SELECT count(*) > v_limit FROM page)
  INTO v_messages, v_has_more
  FROM trimmed;

  SELECT message_count INTO v_latest FROM "cards"."dm_threads" WHERE id = v_thread;
  RETURN jsonb_build_object(
    'thread_id', v_thread,
    'messages', v_messages,
    'has_more', v_has_more,
    'latest_seq', coalesce(v_latest, 0),
    'peer_last_read_seq', coalesce(v_peer_read, 0)
  );
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_dm_messages"(uuid,uuid,bigint,bigint,integer) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_dm_messages"(uuid,uuid,bigint,bigint,integer) TO service_role;--> statement-breakpoint

-- ── Idempotent DM send ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION "cards"."network_send_dm"(
  p_user uuid, p_connection uuid, p_client_id uuid, p_content text
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_thread uuid;
  v_content text;
  v_message cards.dm_messages%ROWTYPE;
  v_duplicate boolean := false;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."connections" c
    WHERE c.id = p_connection AND c.status = 'accepted'
      AND p_user IN (c.requester_user_id, c.recipient_user_id)
  ) THEN
    RETURN jsonb_build_object('error', 'Connection not found', 'status_code', 404);
  END IF;

  v_content := left(btrim(coalesce(p_content, '')), 4000);
  IF v_content = '' THEN
    RETURN jsonb_build_object('error', 'Message cannot be empty', 'status_code', 400);
  END IF;

  SELECT id INTO v_thread FROM "cards"."dm_threads" WHERE connection_id = p_connection;
  IF v_thread IS NULL THEN
    INSERT INTO "cards"."dm_threads" (connection_id) VALUES (p_connection)
    ON CONFLICT (connection_id) DO UPDATE SET connection_id = EXCLUDED.connection_id
    RETURNING id INTO v_thread;
  END IF;

  INSERT INTO "cards"."dm_messages" (thread_id, sender_user_id, content, client_id)
  VALUES (v_thread, p_user, v_content, p_client_id)
  ON CONFLICT (thread_id, sender_user_id, client_id) WHERE client_id IS NOT NULL DO NOTHING
  RETURNING * INTO v_message;

  IF v_message.id IS NULL THEN
    IF p_client_id IS NULL THEN
      RAISE EXCEPTION 'Could not store the message';
    END IF;
    SELECT * INTO v_message FROM "cards"."dm_messages"
    WHERE thread_id = v_thread AND sender_user_id = p_user AND client_id = p_client_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Could not resolve the message';
    END IF;
    v_duplicate := true;
  END IF;

  RETURN jsonb_build_object('message', to_jsonb(v_message), 'duplicate', v_duplicate);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_send_dm"(uuid,uuid,uuid,text) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_send_dm"(uuid,uuid,uuid,text) TO service_role;--> statement-breakpoint

-- ── Group message page ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION "cards"."network_group_messages"(
  p_user uuid, p_group uuid,
  p_before_seq bigint DEFAULT NULL, p_after_seq bigint DEFAULT NULL,
  p_limit integer DEFAULT 50
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_limit integer;
  v_messages jsonb;
  v_has_more boolean;
  v_latest bigint;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members" m
    JOIN "cards"."groups" g ON g.id = m.group_id
    WHERE m.group_id = p_group AND m.user_id = p_user AND g.archived_at IS NULL
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;

  v_limit := greatest(1, least(coalesce(p_limit, 50), 500));

  WITH page AS (
    SELECT id, group_id, seq, client_id, sender_user_id, content, created_at
    FROM "cards"."group_messages"
    WHERE group_id = p_group
      AND (p_before_seq IS NULL OR seq < p_before_seq)
      AND (p_after_seq IS NULL OR seq > p_after_seq)
    ORDER BY seq DESC
    LIMIT v_limit + 1
  ), trimmed AS (
    SELECT * FROM page ORDER BY seq DESC LIMIT v_limit
  )
  SELECT coalesce(jsonb_agg(to_jsonb(trimmed) ORDER BY seq), '[]'::jsonb),
         (SELECT count(*) > v_limit FROM page)
  INTO v_messages, v_has_more
  FROM trimmed;

  SELECT message_count INTO v_latest FROM "cards"."groups" WHERE id = p_group;
  RETURN jsonb_build_object(
    'group_id', p_group,
    'messages', v_messages,
    'has_more', v_has_more,
    'latest_seq', coalesce(v_latest, 0)
  );
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_messages"(uuid,uuid,bigint,bigint,integer) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_messages"(uuid,uuid,bigint,bigint,integer) TO service_role;--> statement-breakpoint

-- ── Idempotent group send ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION "cards"."network_send_group_message"(
  p_user uuid, p_group uuid, p_client_id uuid, p_content text
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_content text;
  v_message cards.group_messages%ROWTYPE;
  v_duplicate boolean := false;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members" m
    JOIN "cards"."groups" g ON g.id = m.group_id
    WHERE m.group_id = p_group AND m.user_id = p_user AND g.archived_at IS NULL
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;

  v_content := left(btrim(coalesce(p_content, '')), 4000);
  IF v_content = '' THEN
    RETURN jsonb_build_object('error', 'Message cannot be empty', 'status_code', 400);
  END IF;

  INSERT INTO "cards"."group_messages" (group_id, sender_user_id, content, client_id)
  VALUES (p_group, p_user, v_content, p_client_id)
  ON CONFLICT (group_id, sender_user_id, client_id) WHERE client_id IS NOT NULL DO NOTHING
  RETURNING * INTO v_message;

  IF v_message.id IS NULL THEN
    IF p_client_id IS NULL THEN
      RAISE EXCEPTION 'Could not store the message';
    END IF;
    SELECT * INTO v_message FROM "cards"."group_messages"
    WHERE group_id = p_group AND sender_user_id = p_user AND client_id = p_client_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Could not resolve the message';
    END IF;
    v_duplicate := true;
  END IF;

  RETURN jsonb_build_object('message', to_jsonb(v_message), 'duplicate', v_duplicate);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_send_group_message"(uuid,uuid,uuid,text) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_send_group_message"(uuid,uuid,uuid,text) TO service_role;--> statement-breakpoint

-- ── Mark-read (also broadcasts a read receipt) ────────────────────────
CREATE OR REPLACE FUNCTION "cards"."network_mark_read"(
  p_user uuid, p_kind text, p_id uuid, p_seq bigint
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_thread uuid;
  v_seq bigint := greatest(coalesce(p_seq, 0), 0);
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;

  IF p_kind = 'dm' THEN
    IF NOT EXISTS (
      SELECT 1 FROM "cards"."connections" c
      WHERE c.id = p_id AND c.status = 'accepted'
        AND p_user IN (c.requester_user_id, c.recipient_user_id)
    ) THEN
      RETURN jsonb_build_object('error', 'Connection not found', 'status_code', 404);
    END IF;
    SELECT id INTO v_thread FROM "cards"."dm_threads" WHERE connection_id = p_id;
    IF v_thread IS NULL THEN
      RETURN jsonb_build_object('error', 'Conversation not found', 'status_code', 404);
    END IF;
    INSERT INTO "cards"."dm_read_state" (thread_id, user_id, last_read_seq, last_read_at)
    VALUES (v_thread, p_user, v_seq, now())
    ON CONFLICT (thread_id, user_id) DO UPDATE
    SET last_read_seq = greatest("cards"."dm_read_state".last_read_seq, EXCLUDED.last_read_seq),
        last_read_at = now();
    BEGIN
      PERFORM realtime.send(
        jsonb_build_object('user_id', p_user, 'last_read_seq', v_seq),
        'read', 'cards:dm:' || v_thread::text, true
      );
    EXCEPTION WHEN OTHERS THEN
      RAISE WARNING 'cards realtime read broadcast failed: %', SQLERRM;
    END;
    RETURN jsonb_build_object('status', 'ok', 'last_read_seq', v_seq);
  END IF;

  IF p_kind = 'group' THEN
    IF NOT EXISTS (
      SELECT 1 FROM "cards"."group_members" m
      JOIN "cards"."groups" g ON g.id = m.group_id
      WHERE m.group_id = p_id AND m.user_id = p_user AND g.archived_at IS NULL
    ) THEN
      RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
    END IF;
    INSERT INTO "cards"."group_read_state" (group_id, user_id, last_read_seq, last_read_at)
    VALUES (p_id, p_user, v_seq, now())
    ON CONFLICT (group_id, user_id) DO UPDATE
    SET last_read_seq = greatest("cards"."group_read_state".last_read_seq, EXCLUDED.last_read_seq),
        last_read_at = now();
    BEGIN
      PERFORM realtime.send(
        jsonb_build_object('user_id', p_user, 'last_read_seq', v_seq),
        'read', 'cards:group:' || p_id::text, true
      );
    EXCEPTION WHEN OTHERS THEN
      RAISE WARNING 'cards realtime read broadcast failed: %', SQLERRM;
    END;
    RETURN jsonb_build_object('status', 'ok', 'last_read_seq', v_seq);
  END IF;

  RETURN jsonb_build_object('error', 'kind must be dm or group', 'status_code', 400);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_mark_read"(uuid,text,uuid,bigint) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_mark_read"(uuid,text,uuid,bigint) TO service_role;--> statement-breakpoint

-- ── Group members with card payloads ─────────────────────────────────
CREATE OR REPLACE FUNCTION "cards"."network_group_members"(p_user uuid, p_group uuid)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_members jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members" m
    JOIN "cards"."groups" g ON g.id = m.group_id
    WHERE m.group_id = p_group AND m.user_id = p_user AND g.archived_at IS NULL
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;

  SELECT coalesce(jsonb_agg(jsonb_build_object(
      'id', m.id,
      'user_id', m.user_id,
      'role', m.role,
      'joined_at', m.joined_at,
      'card', "cards"."network_card_payload"(c.id)
    ) ORDER BY m.joined_at), '[]'::jsonb) INTO v_members
  FROM "cards"."group_members" m
  LEFT JOIN LATERAL (
    SELECT id FROM "cards"."agent_profile_cards"
    WHERE owner_user_id = m.user_id AND status = 'published'
    ORDER BY published_at DESC NULLS LAST
    LIMIT 1
  ) c ON true
  WHERE m.group_id = p_group;

  RETURN jsonb_build_object('members', v_members);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_members"(uuid,uuid) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_members"(uuid,uuid) TO service_role;--> statement-breakpoint

-- ── Triggers: sequence, summary, read state, and broadcast ────────────
CREATE OR REPLACE FUNCTION "cards"."network_dm_thread_read_init"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  INSERT INTO "cards"."dm_read_state" (thread_id, user_id, last_read_seq, last_read_at)
  SELECT NEW.id, p.user_id, 0, now()
  FROM "cards"."connections" c
  CROSS JOIN LATERAL (VALUES (c.requester_user_id), (c.recipient_user_id)) AS p(user_id)
  WHERE c.id = NEW.connection_id
  ON CONFLICT DO NOTHING;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_dm_thread_read_init"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_dm_thread_read_init"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_dm_threads_read_init_trigger"
AFTER INSERT ON "cards"."dm_threads"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_dm_thread_read_init"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_member_read_init"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  INSERT INTO "cards"."group_read_state" (group_id, user_id, last_read_seq, last_read_at)
  SELECT NEW.group_id, NEW.user_id, g.message_count, now()
  FROM "cards"."groups" g WHERE g.id = NEW.group_id
  ON CONFLICT (group_id, user_id) DO UPDATE
  SET last_read_seq = EXCLUDED.last_read_seq, last_read_at = now();
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_member_read_init"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_member_read_init"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_members_read_init_trigger"
AFTER INSERT ON "cards"."group_members"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_member_read_init"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_dm_message_before_insert"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_count bigint;
BEGIN
  NEW.created_at := clock_timestamp();
  -- Lock the parent row so concurrent sends get distinct sequences. The count
  -- is advanced only in the AFTER trigger, after the insert succeeds; an
  -- idempotent retry that hits ON CONFLICT must not consume a sequence.
  SELECT message_count INTO v_count
  FROM "cards"."dm_threads"
  WHERE id = NEW.thread_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'DM thread not found' USING ERRCODE='23503';
  END IF;
  NEW.seq := v_count + 1;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_dm_message_before_insert"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_dm_message_before_insert"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_dm_messages_before_insert_trigger"
BEFORE INSERT ON "cards"."dm_messages"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_dm_message_before_insert"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_dm_message_after_insert"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_connection uuid;
  v_requester uuid;
  v_recipient uuid;
  v_preview text;
BEGIN
  v_preview := left(btrim(regexp_replace(NEW.content, '[[:space:]]+', ' ', 'g')), 140);
  UPDATE "cards"."dm_threads"
  SET message_count = NEW.seq,
      last_message_at = NEW.created_at,
      last_message_preview = v_preview,
      last_message_sender_user_id = NEW.sender_user_id,
      updated_at = NEW.created_at
  WHERE id = NEW.thread_id;

  INSERT INTO "cards"."dm_read_state" (thread_id, user_id, last_read_seq, last_read_at)
  VALUES (NEW.thread_id, NEW.sender_user_id, NEW.seq, now())
  ON CONFLICT (thread_id, user_id) DO UPDATE
  SET last_read_seq = greatest("cards"."dm_read_state".last_read_seq, EXCLUDED.last_read_seq),
      last_read_at = now();

  SELECT t.connection_id, c.requester_user_id, c.recipient_user_id
  INTO v_connection, v_requester, v_recipient
  FROM "cards"."dm_threads" t
  JOIN "cards"."connections" c ON c.id = t.connection_id
  WHERE t.id = NEW.thread_id;

  BEGIN
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'dm', 'connection_id', v_connection, 'thread_id', NEW.thread_id,
        'message', to_jsonb(NEW)
      ),
      'message', 'cards:dm:' || NEW.thread_id::text, true
    );
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'dm', 'connection_id', v_connection, 'thread_id', NEW.thread_id,
        'last_message_at', NEW.created_at, 'last_message_preview', v_preview,
        'last_message_sender_user_id', NEW.sender_user_id, 'seq', NEW.seq
      ),
      'inbox', 'cards:user:' || v_requester::text, true
    );
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'dm', 'connection_id', v_connection, 'thread_id', NEW.thread_id,
        'last_message_at', NEW.created_at, 'last_message_preview', v_preview,
        'last_message_sender_user_id', NEW.sender_user_id, 'seq', NEW.seq
      ),
      'inbox', 'cards:user:' || v_recipient::text, true
    );
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'cards realtime DM broadcast failed: %', SQLERRM;
  END;

  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_dm_message_after_insert"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_dm_message_after_insert"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_dm_messages_after_insert_trigger"
AFTER INSERT ON "cards"."dm_messages"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_dm_message_after_insert"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_message_before_insert"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_count bigint;
BEGIN
  NEW.created_at := clock_timestamp();
  SELECT message_count INTO v_count
  FROM "cards"."groups"
  WHERE id = NEW.group_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Group not found' USING ERRCODE='23503';
  END IF;
  NEW.seq := v_count + 1;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_message_before_insert"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_message_before_insert"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_messages_before_insert_trigger"
BEFORE INSERT ON "cards"."group_messages"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_message_before_insert"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_message_after_insert"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_member uuid;
  v_preview text;
BEGIN
  v_preview := left(btrim(regexp_replace(NEW.content, '[[:space:]]+', ' ', 'g')), 140);
  UPDATE "cards"."groups"
  SET message_count = NEW.seq,
      last_message_at = NEW.created_at,
      last_message_preview = v_preview,
      last_message_sender_user_id = NEW.sender_user_id,
      updated_at = NEW.created_at
  WHERE id = NEW.group_id;

  INSERT INTO "cards"."group_read_state" (group_id, user_id, last_read_seq, last_read_at)
  VALUES (NEW.group_id, NEW.sender_user_id, NEW.seq, now())
  ON CONFLICT (group_id, user_id) DO UPDATE
  SET last_read_seq = greatest("cards"."group_read_state".last_read_seq, EXCLUDED.last_read_seq),
      last_read_at = now();

  BEGIN
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'group', 'group_id', NEW.group_id, 'message', to_jsonb(NEW)
      ),
      'message', 'cards:group:' || NEW.group_id::text, true
    );
    FOR v_member IN SELECT user_id FROM "cards"."group_members" WHERE group_id = NEW.group_id LOOP
      BEGIN
        PERFORM realtime.send(
          jsonb_build_object(
            'kind', 'group', 'group_id', NEW.group_id,
            'last_message_at', NEW.created_at, 'last_message_preview', v_preview,
            'last_message_sender_user_id', NEW.sender_user_id, 'seq', NEW.seq
          ),
          'inbox', 'cards:user:' || v_member::text, true
        );
      EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'cards realtime group inbox broadcast failed for %: %', v_member, SQLERRM;
      END;
    END LOOP;
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'cards realtime group broadcast failed: %', SQLERRM;
  END;

  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_message_after_insert"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_message_after_insert"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_messages_after_insert_trigger"
AFTER INSERT ON "cards"."group_messages"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_message_after_insert"();--> statement-breakpoint

-- ── Connection / invitation / membership events for a live inbox ──────
CREATE OR REPLACE FUNCTION "cards"."network_connection_event"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status) THEN
    BEGIN
      PERFORM realtime.send(
        jsonb_build_object('kind', 'connection', 'connection_id', NEW.id, 'status', NEW.status),
        'connection', 'cards:user:' || NEW.requester_user_id::text, true
      );
      PERFORM realtime.send(
        jsonb_build_object('kind', 'connection', 'connection_id', NEW.id, 'status', NEW.status),
        'connection', 'cards:user:' || NEW.recipient_user_id::text, true
      );
    EXCEPTION WHEN OTHERS THEN
      RAISE WARNING 'cards realtime connection broadcast failed: %', SQLERRM;
    END;
  END IF;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_connection_event"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_connection_event"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_connections_event_trigger"
AFTER INSERT OR UPDATE ON "cards"."connections"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_connection_event"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_invitation_event"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status) THEN
    BEGIN
      PERFORM realtime.send(
        jsonb_build_object('kind', 'invitation', 'invitation_id', NEW.id, 'group_id', NEW.group_id, 'status', NEW.status),
        'invitation', 'cards:user:' || NEW.invitee_user_id::text, true
      );
      PERFORM realtime.send(
        jsonb_build_object('kind', 'invitation', 'invitation_id', NEW.id, 'group_id', NEW.group_id, 'status', NEW.status),
        'invitation', 'cards:user:' || NEW.inviter_user_id::text, true
      );
    EXCEPTION WHEN OTHERS THEN
      RAISE WARNING 'cards realtime invitation broadcast failed: %', SQLERRM;
    END;
  END IF;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_invitation_event"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_invitation_event"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_invitations_event_trigger"
AFTER INSERT OR UPDATE ON "cards"."group_invitations"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_invitation_event"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_member_event"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    BEGIN
      PERFORM realtime.send(
        jsonb_build_object('kind', 'member', 'group_id', NEW.group_id, 'user_id', NEW.user_id, 'role', NEW.role),
        'member', 'cards:group:' || NEW.group_id::text, true
      );
      PERFORM realtime.send(
        jsonb_build_object('kind', 'member', 'group_id', NEW.group_id, 'user_id', NEW.user_id, 'role', NEW.role),
        'member', 'cards:user:' || NEW.user_id::text, true
      );
    EXCEPTION WHEN OTHERS THEN
      RAISE WARNING 'cards realtime member broadcast failed: %', SQLERRM;
    END;
  END IF;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_member_event"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_member_event"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_members_event_trigger"
AFTER INSERT ON "cards"."group_members"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_member_event"();--> statement-breakpoint

-- ── Realtime authorization for private cards:* topics ─────────────────
-- The browser has no table grants in the cards schema. This SECURITY DEFINER
-- function is the only cards object an authenticated browser role may execute;
-- it returns a boolean and never exposes message data.
CREATE OR REPLACE FUNCTION "cards"."network_can_subscribe"(p_topic text)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_user uuid := auth.uid();
  v_kind text;
  v_id uuid;
BEGIN
  -- The caller is always taken from the JWT, never from a function argument,
  -- so a browser cannot probe another user's membership.
  IF v_user IS NULL OR p_topic IS NULL OR p_topic NOT LIKE 'cards:%' THEN
    RETURN false;
  END IF;
  v_kind := split_part(p_topic, ':', 2);
  BEGIN
    v_id := split_part(p_topic, ':', 3)::uuid;
  EXCEPTION WHEN OTHERS THEN
    RETURN false;
  END;
  IF v_kind = 'user' THEN
    RETURN v_id = v_user;
  END IF;
  IF v_kind = 'dm' THEN
    RETURN EXISTS (
      SELECT 1 FROM "cards"."dm_threads" t
      JOIN "cards"."connections" c ON c.id = t.connection_id
      WHERE t.id = v_id AND c.status = 'accepted'
        AND v_user IN (c.requester_user_id, c.recipient_user_id)
    );
  END IF;
  IF v_kind = 'group' THEN
    RETURN EXISTS (
      SELECT 1 FROM "cards"."group_members" m
      JOIN "cards"."groups" g ON g.id = m.group_id
      WHERE m.group_id = v_id AND m.user_id = v_user AND g.archived_at IS NULL
    );
  END IF;
  RETURN false;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_can_subscribe"(text) FROM PUBLIC, anon;--> statement-breakpoint
-- Granting schema usage to `authenticated` also makes every function with the
-- default PUBLIC EXECUTE reachable. Older cards helpers (including the
-- destructive purge_card_events) relied on the schema being closed. Lock the
-- schema down first, then re-grant only the service role and the one boolean
-- Realtime authorization function.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA "cards" FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA "cards" TO service_role;--> statement-breakpoint
REVOKE ALL ON ALL TABLES IN SCHEMA "cards" FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "cards" TO service_role;--> statement-breakpoint
REVOKE ALL ON ALL SEQUENCES IN SCHEMA "cards" FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "cards" TO service_role;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_can_subscribe"(text) TO authenticated, service_role;--> statement-breakpoint
GRANT USAGE ON SCHEMA "cards" TO authenticated;--> statement-breakpoint
DROP POLICY IF EXISTS "cards network can receive broadcasts" ON "realtime"."messages";--> statement-breakpoint
CREATE POLICY "cards network can receive broadcasts"
ON "realtime"."messages" FOR SELECT TO authenticated
USING (
  "realtime"."messages"."extension" = 'broadcast'
  AND "cards"."network_can_subscribe"((SELECT realtime.topic()))
);--> statement-breakpoint
