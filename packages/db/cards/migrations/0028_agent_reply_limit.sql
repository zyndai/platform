-- owner: cards
-- Let a Card assistant reply be up to 8000 characters (it was 4000).
--
-- Assistant replies can now be a full, Markdown-formatted plan or comparison
-- when someone asks for one, and a 4000-character ceiling cut those off. This
-- replaces cards.network_send_agent_group_message with its 0026 definition
-- unchanged except for the limit. Human messages are not affected: DMs and
-- group messages still stop at 4000 (0023), and so do group facts and
-- summaries (0026 CHECK on cards.group_memory). No table, column or grant
-- changes, and the function keeps its signature, so cards-api calls it as
-- before.
--
-- Expand-only and safe to apply before any code change: cards-api keeps
-- GROUP_AGENT_MAX_REPLY_CHARS=4000 until this is applied, then raises it to
-- 8000. Applying it with the old cards-api running changes nothing.
--
-- Rollback (rows already stored stay as they are; only new writes are capped
-- again, and cards-api must go back to GROUP_AGENT_MAX_REPLY_CHARS=4000 first):
--
--   CREATE OR REPLACE FUNCTION "cards"."network_send_agent_group_message"(
--     p_group uuid, p_agent_for uuid, p_content text,
--     p_reply_to uuid DEFAULT NULL, p_client_id uuid DEFAULT NULL
--   )
--   RETURNS jsonb
--   LANGUAGE plpgsql SECURITY DEFINER SET search_path = cards, pg_temp AS $$
--   DECLARE
--     v_content text;
--     v_message cards.group_messages%ROWTYPE;
--     v_duplicate boolean := false;
--   BEGIN
--     IF auth.role() IS DISTINCT FROM 'service_role' THEN
--       RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
--     END IF;
--     IF NOT EXISTS (
--       SELECT 1 FROM "cards"."group_members"
--       WHERE group_id = p_group AND user_id = p_agent_for
--     ) THEN
--       RETURN jsonb_build_object('error', 'Agent owner is not a group member', 'status_code', 403);
--     END IF;
--     IF p_reply_to IS NOT NULL AND NOT EXISTS (
--       SELECT 1 FROM "cards"."group_messages"
--       WHERE id = p_reply_to AND group_id = p_group
--     ) THEN
--       RETURN jsonb_build_object('error', 'Reply target is not in this group', 'status_code', 400);
--     END IF;
--
--     v_content := left(btrim(coalesce(p_content, '')), 4000);
--     IF v_content = '' THEN
--       RETURN jsonb_build_object('error', 'Agent reply cannot be empty', 'status_code', 400);
--     END IF;
--
--     INSERT INTO "cards"."group_messages"
--       (group_id, sender_user_id, sender_kind, agent_for_user_id, reply_to_message_id, content, client_id)
--     VALUES
--       (p_group, p_agent_for, 'agent', p_agent_for, p_reply_to, v_content, p_client_id)
--     ON CONFLICT (group_id, sender_user_id, client_id) WHERE client_id IS NOT NULL DO NOTHING
--     RETURNING * INTO v_message;
--
--     IF v_message.id IS NULL THEN
--       IF p_client_id IS NULL THEN
--         RAISE EXCEPTION 'Could not store the agent reply';
--       END IF;
--       SELECT * INTO v_message FROM "cards"."group_messages"
--       WHERE group_id = p_group AND sender_user_id = p_agent_for AND client_id = p_client_id;
--       IF NOT FOUND THEN
--         RAISE EXCEPTION 'Could not resolve the agent reply';
--       END IF;
--       v_duplicate := true;
--     END IF;
--
--     RETURN jsonb_build_object('message', to_jsonb(v_message), 'duplicate', v_duplicate);
--   END $$;
--   REVOKE ALL ON FUNCTION "cards"."network_send_agent_group_message"(uuid,uuid,text,uuid,uuid) FROM PUBLIC, anon, authenticated;
--   GRANT EXECUTE ON FUNCTION "cards"."network_send_agent_group_message"(uuid,uuid,text,uuid,uuid) TO service_role;

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

  v_content := left(btrim(coalesce(p_content, '')), 8000);
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
