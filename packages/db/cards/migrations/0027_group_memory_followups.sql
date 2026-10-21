-- owner: cards
-- Follow-up fixes for the group memory / Card assistant feature.
--
-- 1. An assistant reply must not advance the tagged member's read cursor.
-- 2. A worker crash must not leave a job "running" forever.
-- 3. A failed attempt that will retry should stay "pending" instead of
--    flashing "failed" in the UI.
-- 4. Embedding backfills must not re-broadcast the full summary/fact.
-- 5. Assistant replies cannot be turned into durable group facts.
--
-- Rollback: restore the 0026 definitions of the replaced functions and the
-- trigger, which fired on every INSERT/UPDATE.

-- ── Read state: only a human-authored message is "sent" by that member ──
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

  IF NEW.sender_kind = 'user' THEN
    INSERT INTO "cards"."group_read_state" (group_id, user_id, last_read_seq, last_read_at)
    VALUES (NEW.group_id, NEW.sender_user_id, NEW.seq, now())
    ON CONFLICT (group_id, user_id) DO UPDATE
    SET last_read_seq = greatest("cards"."group_read_state".last_read_seq, EXCLUDED.last_read_seq),
        last_read_at = now();
  END IF;

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

-- ── Reclaim jobs whose worker died while "running" ─────────────────────
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
  WHERE attempts < 3
    AND (
      (status IN ('pending', 'failed') AND available_at <= now())
      OR (status = 'running' AND locked_at < now() - interval '5 minutes')
    )
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

-- ── Retry quietly; only the final failed attempt is a failure ──────────
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
  SET status = CASE
        WHEN p_ok THEN 'done'
        WHEN attempts >= 3 THEN 'failed'
        ELSE 'pending'
      END,
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

-- ── Never remember an assistant reply as a durable fact ────────────────
CREATE OR REPLACE FUNCTION "cards"."network_group_memory_remember"(
  p_user uuid, p_group uuid, p_message uuid, p_content_hash text,
  p_embedding vector(1536) DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
DECLARE
  v_content text;
  v_sender_kind text;
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
  SELECT left(btrim(content), 4000), sender_kind INTO v_content, v_sender_kind
  FROM "cards"."group_messages"
  WHERE id = p_message AND group_id = p_group;
  IF NOT FOUND OR v_content = '' THEN
    RETURN jsonb_build_object('error', 'Message not found', 'status_code', 404);
  END IF;
  IF v_sender_kind = 'agent' THEN
    RETURN jsonb_build_object('error', 'Assistant replies cannot be saved as group facts', 'status_code', 422);
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

-- ── Broadcast only when content changes, not on embedding backfills ────
DROP TRIGGER IF EXISTS "cards_group_memory_event_trigger" ON "cards"."group_memory";--> statement-breakpoint
CREATE TRIGGER "cards_group_memory_event_trigger"
AFTER INSERT OR UPDATE OF content ON "cards"."group_memory"
FOR EACH ROW EXECUTE FUNCTION "cards"."network_group_memory_event"();--> statement-breakpoint
