-- owner: cards
-- Per-group durable memory and Card AI assistant replies.
--
-- The conversation itself is not copied into memory: agents receive the last
-- N messages as raw context. group_memory stores only the rolling summary and
-- the small set of durable facts (including messages a member explicitly
-- remembers). The new tables are service-role-only; the browser keeps going
-- through cards-api and Realtime Broadcast.
--
-- Rollback: drop the new triggers/functions, the new tables, and the four
-- columns added to group_messages. Message rows are never dropped.

CREATE TABLE "cards"."group_agent_jobs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"message_id" uuid NOT NULL,
	"mentioned_user_id" uuid NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"attempts" integer DEFAULT 0 NOT NULL,
	"available_at" timestamp with time zone DEFAULT now() NOT NULL,
	"locked_at" timestamp with time zone,
	"last_error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_group_agent_jobs_status_check" CHECK (status IN ('pending', 'running', 'done', 'failed'))
);
--> statement-breakpoint
ALTER TABLE "cards"."group_agent_jobs" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_agent_preferences" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."group_agent_preferences" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_memory" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"group_id" uuid NOT NULL,
	"kind" text NOT NULL,
	"content" text NOT NULL,
	"content_hash" text NOT NULL,
	"source_message_id" uuid,
	"created_by" uuid,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"embedding" vector(1536),
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_group_memory_kind_check" CHECK (kind IN ('summary', 'fact')),
	CONSTRAINT "cards_group_memory_content_check" CHECK (char_length(content) BETWEEN 1 AND 4000)
);
--> statement-breakpoint
ALTER TABLE "cards"."group_memory" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_memory_state" (
	"group_id" uuid PRIMARY KEY NOT NULL,
	"last_summarized_seq" bigint DEFAULT 0 NOT NULL,
	"summary_memory_id" uuid,
	"summary_updated_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cards_group_memory_state_seq_check" CHECK (last_summarized_seq >= 0)
);
--> statement-breakpoint
ALTER TABLE "cards"."group_memory_state" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "cards"."group_message_memory" (
	"message_id" uuid PRIMARY KEY NOT NULL,
	"memory_id" uuid NOT NULL,
	"created_by" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "cards"."group_message_memory" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD COLUMN "sender_kind" text DEFAULT 'user' NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD COLUMN "agent_for_user_id" uuid;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD COLUMN "reply_to_message_id" uuid;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD COLUMN "mentions" uuid[] DEFAULT '{}'::uuid[] NOT NULL;--> statement-breakpoint
ALTER TABLE "cards"."group_agent_jobs" ADD CONSTRAINT "cards_group_agent_jobs_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_agent_jobs" ADD CONSTRAINT "cards_group_agent_jobs_message_fkey" FOREIGN KEY ("message_id") REFERENCES "cards"."group_messages"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_agent_jobs" ADD CONSTRAINT "cards_group_agent_jobs_user_fkey" FOREIGN KEY ("mentioned_user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_agent_preferences" ADD CONSTRAINT "cards_group_agent_preferences_user_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_memory" ADD CONSTRAINT "cards_group_memory_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_memory" ADD CONSTRAINT "cards_group_memory_source_message_fkey" FOREIGN KEY ("source_message_id") REFERENCES "cards"."group_messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_memory" ADD CONSTRAINT "cards_group_memory_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_memory_state" ADD CONSTRAINT "cards_group_memory_state_group_fkey" FOREIGN KEY ("group_id") REFERENCES "cards"."groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_memory_state" ADD CONSTRAINT "cards_group_memory_state_summary_fkey" FOREIGN KEY ("summary_memory_id") REFERENCES "cards"."group_memory"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_message_memory" ADD CONSTRAINT "cards_group_message_memory_message_fkey" FOREIGN KEY ("message_id") REFERENCES "cards"."group_messages"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_message_memory" ADD CONSTRAINT "cards_group_message_memory_memory_fkey" FOREIGN KEY ("memory_id") REFERENCES "cards"."group_memory"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_message_memory" ADD CONSTRAINT "cards_group_message_memory_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "cards_group_agent_jobs_message_user_key" ON "cards"."group_agent_jobs" USING btree ("message_id","mentioned_user_id");--> statement-breakpoint
CREATE INDEX "cards_group_agent_jobs_ready_idx" ON "cards"."group_agent_jobs" USING btree ("status","available_at");--> statement-breakpoint
CREATE INDEX "cards_group_agent_jobs_group_idx" ON "cards"."group_agent_jobs" USING btree ("group_id","created_at" DESC NULLS LAST);--> statement-breakpoint
CREATE UNIQUE INDEX "cards_group_memory_summary_key" ON "cards"."group_memory" USING btree ("group_id") WHERE kind = 'summary';--> statement-breakpoint
CREATE UNIQUE INDEX "cards_group_memory_fact_hash_key" ON "cards"."group_memory" USING btree ("group_id","content_hash") WHERE kind = 'fact';--> statement-breakpoint
CREATE INDEX "cards_group_memory_group_created_idx" ON "cards"."group_memory" USING btree ("group_id","created_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "cards_group_memory_embedding_hnsw_idx" ON "cards"."group_memory" USING hnsw ("embedding" vector_cosine_ops);--> statement-breakpoint
CREATE INDEX "cards_group_message_memory_memory_idx" ON "cards"."group_message_memory" USING btree ("memory_id");--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_agent_for_user_id_fkey" FOREIGN KEY ("agent_for_user_id") REFERENCES "auth"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_reply_to_message_id_fkey" FOREIGN KEY ("reply_to_message_id") REFERENCES "cards"."group_messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_sender_kind_check" CHECK (sender_kind IN ('user', 'agent'));--> statement-breakpoint
ALTER TABLE "cards"."group_messages" ADD CONSTRAINT "cards_group_messages_agent_identity_check" CHECK (sender_kind = 'user' OR agent_for_user_id IS NOT NULL);--> statement-breakpoint
CREATE POLICY "service role full access on group_agent_jobs" ON "cards"."group_agent_jobs" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_agent_preferences" ON "cards"."group_agent_preferences" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_memory" ON "cards"."group_memory" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_memory_state" ON "cards"."group_memory_state" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint
CREATE POLICY "service role full access on group_message_memory" ON "cards"."group_message_memory" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);--> statement-breakpoint

-- ── Message page includes the memory highlight + agent identity ───────
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
    SELECT m.id, m.group_id, m.seq, m.client_id, m.sender_user_id,
           m.sender_kind, m.agent_for_user_id, m.reply_to_message_id, m.mentions,
           m.content, m.created_at,
           (mm.memory_id IS NOT NULL) AS remembered,
           mm.memory_id
    FROM "cards"."group_messages" m
    LEFT JOIN "cards"."group_message_memory" mm ON mm.message_id = m.id
    WHERE m.group_id = p_group
      AND (p_before_seq IS NULL OR m.seq < p_before_seq)
      AND (p_after_seq IS NULL OR m.seq > p_after_seq)
    ORDER BY m.seq DESC
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

-- ── Write an assistant reply, visibly attributed to the Card assistant ─
CREATE OR REPLACE FUNCTION "cards"."network_send_agent_group_message"(
  p_group uuid, p_agent_for uuid, p_content text,
  p_reply_to uuid DEFAULT NULL, p_client_id uuid DEFAULT NULL
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
    SELECT 1 FROM "cards"."group_members"
    WHERE group_id = p_group AND user_id = p_agent_for
  ) THEN
    RETURN jsonb_build_object('error', 'Agent owner is not a group member', 'status_code', 403);
  END IF;
  IF p_reply_to IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM "cards"."group_messages"
    WHERE id = p_reply_to AND group_id = p_group
  ) THEN
    RETURN jsonb_build_object('error', 'Reply target is not in this group', 'status_code', 400);
  END IF;

  v_content := left(btrim(coalesce(p_content, '')), 4000);
  IF v_content = '' THEN
    RETURN jsonb_build_object('error', 'Agent reply cannot be empty', 'status_code', 400);
  END IF;

  INSERT INTO "cards"."group_messages"
    (group_id, sender_user_id, sender_kind, agent_for_user_id, reply_to_message_id, content, client_id)
  VALUES
    (p_group, p_agent_for, 'agent', p_agent_for, p_reply_to, v_content, p_client_id)
  ON CONFLICT (group_id, sender_user_id, client_id) WHERE client_id IS NOT NULL DO NOTHING
  RETURNING * INTO v_message;

  IF v_message.id IS NULL THEN
    IF p_client_id IS NULL THEN
      RAISE EXCEPTION 'Could not store the agent reply';
    END IF;
    SELECT * INTO v_message FROM "cards"."group_messages"
    WHERE group_id = p_group AND sender_user_id = p_agent_for AND client_id = p_client_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Could not resolve the agent reply';
    END IF;
    v_duplicate := true;
  END IF;

  RETURN jsonb_build_object('message', to_jsonb(v_message), 'duplicate', v_duplicate);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_send_agent_group_message"(uuid,uuid,text,uuid,uuid) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_send_agent_group_message"(uuid,uuid,text,uuid,uuid) TO service_role;--> statement-breakpoint

-- ── Inbox preview keeps AI replies visibly separate from the person ───
CREATE OR REPLACE FUNCTION "cards"."network_group_message_after_insert"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_member uuid;
  v_preview text;
BEGIN
  v_preview := left(btrim(regexp_replace(NEW.content, '[[:space:]]+', ' ', 'g')), 140);
  IF NEW.sender_kind = 'agent' THEN
    v_preview := 'AI: ' || v_preview;
  END IF;
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

-- ── Durable mention jobs; agent replies never create more jobs ─────────
CREATE OR REPLACE FUNCTION "cards"."network_enqueue_group_agent_replies"(
  p_message uuid, p_users uuid[]
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_group uuid;
  v_sender uuid;
  v_user uuid;
  v_users uuid[];
  v_count integer := 0;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  SELECT group_id, sender_user_id INTO v_group, v_sender
  FROM "cards"."group_messages" WHERE id = p_message;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', 'Message not found', 'status_code', 404);
  END IF;

  v_users := coalesce(p_users, '{}'::uuid[]);
  v_users := v_users[1:2];       -- two agents per message is plenty
  FOREACH v_user IN ARRAY v_users LOOP
    IF v_user IS NULL OR v_user = v_sender THEN
      CONTINUE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM "cards"."group_members"
      WHERE group_id = v_group AND user_id = v_user
    ) THEN
      CONTINUE;
    END IF;
    IF EXISTS (
      SELECT 1 FROM "cards"."group_agent_preferences"
      WHERE user_id = v_user AND enabled = false
    ) THEN
      CONTINUE;
    END IF;
    -- A short cooldown stops a rapid-fire mention from spawning a queue.
    IF EXISTS (
      SELECT 1 FROM "cards"."group_agent_jobs"
      WHERE group_id = v_group AND mentioned_user_id = v_user
        AND created_at > now() - interval '10 seconds'
    ) THEN
      CONTINUE;
    END IF;
    INSERT INTO "cards"."group_agent_jobs" (group_id, message_id, mentioned_user_id)
    VALUES (v_group, p_message, v_user)
    ON CONFLICT (message_id, mentioned_user_id) DO NOTHING;
    IF FOUND THEN
      v_count := v_count + 1;
    END IF;
  END LOOP;

  RETURN jsonb_build_object('enqueued', v_count);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_enqueue_group_agent_replies"(uuid,uuid[]) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_enqueue_group_agent_replies"(uuid,uuid[]) TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_claim_group_agent_job"()
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_job cards.group_agent_jobs%ROWTYPE;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;

  SELECT * INTO v_job
  FROM "cards"."group_agent_jobs"
  WHERE status IN ('pending', 'failed')
    AND attempts < 3
    AND available_at <= now()
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  UPDATE "cards"."group_agent_jobs"
  SET status = 'running', attempts = attempts + 1, locked_at = now(), updated_at = now()
  WHERE id = v_job.id
  RETURNING * INTO v_job;
  RETURN to_jsonb(v_job);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_claim_group_agent_job"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_claim_group_agent_job"() TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_finish_group_agent_job"(
  p_job uuid, p_ok boolean, p_error text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_job cards.group_agent_jobs%ROWTYPE;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  UPDATE "cards"."group_agent_jobs"
  SET status = CASE WHEN p_ok THEN 'done' ELSE 'failed' END,
      last_error = CASE WHEN p_ok THEN NULL ELSE left(coalesce(p_error, 'Agent failed'), 1000) END,
      locked_at = NULL,
      available_at = CASE WHEN p_ok THEN now() ELSE now() + interval '30 seconds' END,
      updated_at = now()
  WHERE id = p_job
  RETURNING * INTO v_job;
  RETURN to_jsonb(v_job);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_finish_group_agent_job"(uuid,boolean,text) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_finish_group_agent_job"(uuid,boolean,text) TO service_role;--> statement-breakpoint

-- ── Semantic search over summaries + facts, never raw messages ─────────
CREATE OR REPLACE FUNCTION "cards"."network_group_memory_search"(
  p_user uuid, p_group uuid, p_query_embedding vector(1536), p_limit integer DEFAULT 8
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, extensions, pg_temp AS $$
DECLARE
  v_limit integer;
  v_results jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members"
    WHERE group_id = p_group AND user_id = p_user
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;
  IF p_query_embedding IS NULL THEN
    RETURN '[]'::jsonb;
  END IF;

  v_limit := greatest(1, least(coalesce(p_limit, 8), 20));
  SELECT coalesce(jsonb_agg(jsonb_build_object(
      'id', s.id,
      'kind', s.kind,
      'content', s.content,
      'metadata', s.metadata,
      'created_at', s.created_at,
      'similarity', round(s.similarity::numeric, 4)
    ) ORDER BY s.similarity DESC), '[]'::jsonb)
  INTO v_results
  FROM (
    SELECT id, kind, content, metadata, created_at,
           1 - (embedding <=> p_query_embedding) AS similarity
    FROM "cards"."group_memory"
    WHERE group_id = p_group AND embedding IS NOT NULL
    ORDER BY embedding <=> p_query_embedding
    LIMIT v_limit
  ) s;
  RETURN v_results;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_memory_search"(uuid,uuid,vector,integer) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_memory_search"(uuid,uuid,vector,integer) TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_memory_list"(
  p_user uuid, p_group uuid, p_limit integer DEFAULT 30
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_limit integer;
  v_summary jsonb;
  v_facts jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members"
    WHERE group_id = p_group AND user_id = p_user
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;

  v_limit := greatest(1, least(coalesce(p_limit, 30), 100));
  SELECT to_jsonb(s) INTO v_summary
  FROM (
    SELECT id, kind, content, metadata, created_at, updated_at
    FROM "cards"."group_memory"
    WHERE group_id = p_group AND kind = 'summary'
    LIMIT 1
  ) s;
  SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.created_at DESC), '[]'::jsonb) INTO v_facts
  FROM (
    SELECT id, kind, content, metadata, source_message_id, created_at
    FROM "cards"."group_memory"
    WHERE group_id = p_group AND kind = 'fact'
    ORDER BY created_at DESC
    LIMIT v_limit
  ) f;

  RETURN jsonb_build_object('summary', v_summary, 'facts', v_facts);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_memory_list"(uuid,uuid,integer) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_memory_list"(uuid,uuid,integer) TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_memory_remember"(
  p_user uuid, p_group uuid, p_message uuid, p_content_hash text,
  p_embedding vector(1536) DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_content text;
  v_memory cards.group_memory%ROWTYPE;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members"
    WHERE group_id = p_group AND user_id = p_user
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;
  SELECT left(btrim(content), 4000) INTO v_content
  FROM "cards"."group_messages"
  WHERE id = p_message AND group_id = p_group;
  IF NOT FOUND OR v_content = '' THEN
    RETURN jsonb_build_object('error', 'Message not found', 'status_code', 404);
  END IF;

  INSERT INTO "cards"."group_memory"
    (group_id, kind, content, content_hash, source_message_id, created_by, metadata, embedding)
  VALUES
    (p_group, 'fact', v_content, p_content_hash, p_message, p_user,
     jsonb_build_object('source', 'remember', 'message_id', p_message), p_embedding)
  ON CONFLICT (group_id, content_hash) WHERE kind = 'fact' DO UPDATE
  SET updated_at = now(),
      source_message_id = coalesce(excluded.source_message_id, "cards"."group_memory".source_message_id),
      metadata = "cards"."group_memory".metadata || excluded.metadata,
      embedding = coalesce(excluded.embedding, "cards"."group_memory".embedding)
  RETURNING * INTO v_memory;

  INSERT INTO "cards"."group_message_memory" (message_id, memory_id, created_by)
  VALUES (p_message, v_memory.id, p_user)
  ON CONFLICT (message_id) DO UPDATE
  SET memory_id = excluded.memory_id, created_by = excluded.created_by;

  RETURN jsonb_build_object('memory', jsonb_build_object(
    'id', v_memory.id, 'kind', v_memory.kind, 'content', v_memory.content,
    'metadata', v_memory.metadata, 'source_message_id', v_memory.source_message_id,
    'created_at', v_memory.created_at, 'updated_at', v_memory.updated_at
  ), 'message_id', p_message);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_memory_remember"(uuid,uuid,uuid,text,vector) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_memory_remember"(uuid,uuid,uuid,text,vector) TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_memory_add_fact"(
  p_user uuid, p_group uuid, p_content text, p_content_hash text,
  p_embedding vector(1536) DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_content text;
  v_memory cards.group_memory%ROWTYPE;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM "cards"."group_members"
    WHERE group_id = p_group AND user_id = p_user
  ) THEN
    RETURN jsonb_build_object('error', 'Group not found', 'status_code', 404);
  END IF;
  v_content := left(btrim(coalesce(p_content, '')), 4000);
  IF v_content = '' THEN
    RETURN jsonb_build_object('error', 'Fact cannot be empty', 'status_code', 400);
  END IF;

  INSERT INTO "cards"."group_memory"
    (group_id, kind, content, content_hash, created_by, metadata, embedding)
  VALUES
    (p_group, 'fact', v_content, p_content_hash, p_user,
     jsonb_build_object('source', 'manual'), p_embedding)
  ON CONFLICT (group_id, content_hash) WHERE kind = 'fact' DO UPDATE
  SET updated_at = now(),
      metadata = "cards"."group_memory".metadata || excluded.metadata,
      embedding = coalesce(excluded.embedding, "cards"."group_memory".embedding)
  RETURNING * INTO v_memory;

  RETURN jsonb_build_object('memory', jsonb_build_object(
    'id', v_memory.id, 'kind', v_memory.kind, 'content', v_memory.content,
    'metadata', v_memory.metadata, 'source_message_id', v_memory.source_message_id,
    'created_at', v_memory.created_at, 'updated_at', v_memory.updated_at
  ));
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_memory_add_fact"(uuid,uuid,text,text,vector) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_memory_add_fact"(uuid,uuid,text,text,vector) TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_memory_set_summary"(
  p_group uuid, p_content text, p_content_hash text, p_through_seq bigint,
  p_embedding vector(1536) DEFAULT NULL, p_metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_memory cards.group_memory%ROWTYPE;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;

  INSERT INTO "cards"."group_memory"
    (group_id, kind, content, content_hash, metadata, embedding)
  VALUES
    (p_group, 'summary', left(btrim(p_content), 4000), p_content_hash,
     coalesce(p_metadata, '{}'::jsonb), p_embedding)
  ON CONFLICT (group_id) WHERE kind = 'summary' DO UPDATE
  SET content = excluded.content,
      content_hash = excluded.content_hash,
      metadata = excluded.metadata,
      embedding = coalesce(excluded.embedding, "cards"."group_memory".embedding),
      updated_at = now()
  RETURNING * INTO v_memory;

  INSERT INTO "cards"."group_memory_state"
    (group_id, last_summarized_seq, summary_memory_id, summary_updated_at)
  VALUES
    (p_group, greatest(coalesce(p_through_seq, 0), 0), v_memory.id, now())
  ON CONFLICT (group_id) DO UPDATE
  SET last_summarized_seq = greatest("cards"."group_memory_state".last_summarized_seq, excluded.last_summarized_seq),
      summary_memory_id = excluded.summary_memory_id,
      summary_updated_at = now(),
      updated_at = now();

  RETURN jsonb_build_object('memory', jsonb_build_object(
    'id', v_memory.id, 'kind', v_memory.kind, 'content', v_memory.content,
    'metadata', v_memory.metadata, 'created_at', v_memory.created_at,
    'updated_at', v_memory.updated_at
  ), 'through_seq', p_through_seq);
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_memory_set_summary"(uuid,text,text,bigint,vector,jsonb) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_memory_set_summary"(uuid,text,text,bigint,vector,jsonb) TO service_role;--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_groups_needing_summary"(
  p_min_messages integer DEFAULT 30, p_limit integer DEFAULT 5
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_limit integer;
  v_min integer;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  v_min := greatest(1, coalesce(p_min_messages, 30));
  v_limit := greatest(1, least(coalesce(p_limit, 5), 20));
  RETURN (
    SELECT coalesce(jsonb_agg(jsonb_build_object(
      'group_id', s.id,
      'message_count', s.message_count,
      'last_summarized_seq', s.last_summarized_seq
    ) ORDER BY s.updated_at), '[]'::jsonb)
    FROM (
      SELECT g.id, g.message_count, coalesce(st.last_summarized_seq, 0) AS last_summarized_seq, g.updated_at
      FROM "cards"."groups" g
      LEFT JOIN "cards"."group_memory_state" st ON st.group_id = g.id
      WHERE g.archived_at IS NULL
        AND g.message_count > coalesce(st.last_summarized_seq, 0)
        AND g.message_count - coalesce(st.last_summarized_seq, 0) >= v_min
      ORDER BY g.updated_at
      LIMIT v_limit
    ) s
  );
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_groups_needing_summary"(integer,integer) FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_groups_needing_summary"(integer,integer) TO service_role;--> statement-breakpoint

-- ── Realtime hints: memory saved, agent thinking ───────────────────────
CREATE OR REPLACE FUNCTION "cards"."network_group_memory_event"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  BEGIN
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'group_memory', 'group_id', NEW.group_id, 'memory_id', NEW.id,
        'memory_kind', NEW.kind, 'content', NEW.content,
        'source_message_id', NEW.source_message_id
      ),
      'memory', 'cards:group:' || NEW.group_id::text, true
    );
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'cards group memory broadcast failed: %', SQLERRM;
  END;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_memory_event"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_memory_event"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_memory_event_trigger"
AFTER INSERT OR UPDATE ON "cards"."group_memory"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_memory_event"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_message_memory_event"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_group uuid;
BEGIN
  SELECT group_id INTO v_group FROM "cards"."group_messages" WHERE id = NEW.message_id;
  IF v_group IS NULL THEN
    RETURN NEW;
  END IF;
  BEGIN
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'group_memory_link', 'group_id', v_group,
        'message_id', NEW.message_id, 'memory_id', NEW.memory_id
      ),
      'memory', 'cards:group:' || v_group::text, true
    );
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'cards group memory link broadcast failed: %', SQLERRM;
  END;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_message_memory_event"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_message_memory_event"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_message_memory_event_trigger"
AFTER INSERT OR UPDATE ON "cards"."group_message_memory"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_message_memory_event"();--> statement-breakpoint

CREATE OR REPLACE FUNCTION "cards"."network_group_agent_job_event"()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
BEGIN
  BEGIN
    PERFORM realtime.send(
      jsonb_build_object(
        'kind', 'agent_typing', 'job_id', NEW.id, 'group_id', NEW.group_id,
        'message_id', NEW.message_id, 'user_id', NEW.mentioned_user_id,
        'status', NEW.status
      ),
      'agent_typing', 'cards:group:' || NEW.group_id::text, true
    );
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'cards group agent typing broadcast failed: %', SQLERRM;
  END;
  RETURN NEW;
END $$;--> statement-breakpoint
REVOKE ALL ON FUNCTION "cards"."network_group_agent_job_event"() FROM PUBLIC, anon, authenticated;--> statement-breakpoint
GRANT EXECUTE ON FUNCTION "cards"."network_group_agent_job_event"() TO service_role;--> statement-breakpoint
CREATE TRIGGER "cards_group_agent_job_event_trigger"
AFTER INSERT OR UPDATE OF status ON "cards"."group_agent_jobs"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_agent_job_event"();