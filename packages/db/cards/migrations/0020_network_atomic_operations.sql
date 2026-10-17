-- owner: cards
-- Resolve invitations and create groups transactionally. Expiry, concurrent
-- decisions, and the 50-member limit must not leave membership out of sync.
-- Rollback: revert the API first; retain the additive tables/data, then optionally
-- DROP FUNCTION cards.network_respond_invitation(uuid,uuid,text);
-- DROP FUNCTION cards.network_create_group(uuid,text,text,text);

CREATE FUNCTION cards.network_create_group(p_user uuid,p_name text,p_description text,p_visibility text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE created cards.groups;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF p_user IS NULL OR coalesce(trim(p_name),'')='' OR p_visibility IS NULL OR p_visibility NOT IN ('private','open') THEN
    RETURN jsonb_build_object('error','Invalid group','status_code',400);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM cards.agent_profile_cards
                 WHERE owner_user_id=p_user AND owner_email IS NOT NULL AND status='published') THEN
    RETURN jsonb_build_object('error','You need a claimed, published Card before using Connections','status_code',409);
  END IF;
  INSERT INTO cards.groups(name,description,owner_user_id,visibility)
    VALUES(left(trim(p_name),80),nullif(left(trim(p_description),500),''),p_user,p_visibility)
    RETURNING * INTO created;
  INSERT INTO cards.group_members(group_id,user_id,role) VALUES(created.id,p_user,'owner');
  RETURN jsonb_build_object('group',to_jsonb(created));
END $$;
--> statement-breakpoint
CREATE FUNCTION cards.network_respond_invitation(p_user uuid,p_invitation uuid,p_decision text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=cards,pg_temp AS $$
DECLARE invitation cards.group_invitations; target_group uuid; active_group cards.groups; connection_id uuid;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE EXCEPTION 'Service only' USING ERRCODE='42501';
  END IF;
  IF p_decision IS NULL OR p_decision NOT IN ('accept','decline') THEN
    RETURN jsonb_build_object('error','decision must be accept or decline','status_code',400);
  END IF;
  SELECT group_id INTO target_group FROM cards.group_invitations WHERE id=p_invitation AND invitee_user_id=p_user;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error','Invitation not found','status_code',404);
  END IF;
  -- All decisions for a group acquire the same lock before checking capacity.
  -- Reading expiry AFTER taking the lock prevents acceptance after waiting.
  SELECT * INTO active_group FROM cards.groups WHERE id=target_group AND archived_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error','Group not found','status_code',404);
  END IF;
  SELECT * INTO invitation FROM cards.group_invitations WHERE id=p_invitation AND invitee_user_id=p_user FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error','Invitation not found','status_code',404);
  END IF;
  IF invitation.status <> 'pending' THEN
    RETURN jsonb_build_object('error','Invitation already resolved','status_code',409);
  END IF;
  IF invitation.expires_at <= clock_timestamp() THEN
    UPDATE cards.group_invitations SET status='expired',decided_at=clock_timestamp() WHERE id=p_invitation;
    RETURN jsonb_build_object('error','Invitation expired','status_code',409);
  END IF;
  IF p_decision='decline' THEN
    UPDATE cards.group_invitations SET status='declined',decided_at=clock_timestamp() WHERE id=p_invitation;
    RETURN jsonb_build_object('status','declined','group_id',target_group);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM cards.agent_profile_cards
                 WHERE owner_user_id=p_user AND owner_email IS NOT NULL AND status='published') THEN
    RETURN jsonb_build_object('error','You need a claimed, published Card before joining','status_code',409);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM cards.group_members WHERE group_id=target_group
                 AND user_id=invitation.inviter_user_id AND role='owner') THEN
    RETURN jsonb_build_object('error','The inviter no longer manages this group','status_code',409);
  END IF;
  SELECT id INTO connection_id FROM cards.connections
    WHERE connection_key=least(p_user::text,invitation.inviter_user_id::text)||':'||greatest(p_user::text,invitation.inviter_user_id::text)
      AND status='accepted' FOR SHARE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error','Invitees must be an accepted Card connection','status_code',409);
  END IF;
  IF EXISTS (SELECT 1 FROM cards.group_members WHERE group_id=target_group AND user_id=p_user) THEN
    RETURN jsonb_build_object('error','You are already a group member','status_code',409);
  END IF;
  IF (SELECT count(*) FROM cards.group_members WHERE group_id=target_group) >= 50 THEN
    RETURN jsonb_build_object('error','This group is full','status_code',409);
  END IF;
  INSERT INTO cards.group_members(group_id,user_id,role,invited_by)
    VALUES(target_group,p_user,'member',invitation.inviter_user_id);
  UPDATE cards.group_invitations SET status='accepted',decided_at=clock_timestamp() WHERE id=p_invitation;
  UPDATE cards.groups SET updated_at=clock_timestamp() WHERE id=target_group;
  RETURN jsonb_build_object('status','accepted','group_id',target_group);
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION cards.network_create_group(uuid,text,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION cards.network_respond_invitation(uuid,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION cards.network_create_group(uuid,text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION cards.network_respond_invitation(uuid,uuid,text) TO service_role;
