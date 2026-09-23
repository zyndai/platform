-- Zynd AI — RLS policies, realtime publication, and partial indexes.
--
-- Prisma manages tables / columns / enums / regular indexes from
-- schema.prisma. The objects below are NOT expressible in Prisma syntax,
-- so they live here as a side-car migration applied after each
-- `prisma migrate deploy`.
--
-- Apply this file once per environment after the initial migration, AND
-- after any future migration that creates new tables (you can re-run this
-- file safely — every statement uses IF NOT EXISTS or DROP-then-CREATE).

-- ====================================================================
-- 1. ENABLE ROW LEVEL SECURITY on every public table.
-- Prisma creates the tables; we flip RLS on here.
-- ====================================================================
ALTER TABLE public.api_tokens                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.persona_agents             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dm_threads                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dm_messages                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_tasks                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.a2a_tasks                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pending_approvals          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.telegram_links             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.telegram_chat_history      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.linkedin_profiles          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.brief_todos                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outbound_callbacks         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.callback_results           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.persona_groups             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.persona_group_members      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.persona_group_messages     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.persona_group_constraints  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.persona_group_audit_events ENABLE ROW LEVEL SECURITY;

-- ====================================================================
-- 1b. SECURITY-DEFINER HELPERS FOR GROUP MEMBERSHIP
-- ====================================================================
-- RLS policies that query persona_group_members directly can recurse
-- when the roster table's own policy is being evaluated. Keep the
-- membership lookup behind security-definer helpers owned by the
-- migration role, so policies on groups/messages/constraints/realtime
-- can ask a simple yes/no question without re-entering roster RLS.
CREATE OR REPLACE FUNCTION public.is_persona_group_member(
    check_group_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT auth.uid() IS NOT NULL
       AND EXISTS (
            SELECT 1
              FROM public.persona_group_members m
             WHERE m.group_id = check_group_id
               AND m.user_id = auth.uid()
        );
$$;

CREATE OR REPLACE FUNCTION public.is_persona_group_manager(
    check_group_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT auth.uid() IS NOT NULL
       AND EXISTS (
            SELECT 1
              FROM public.persona_group_members m
             WHERE m.group_id = check_group_id
               AND m.user_id = auth.uid()
               AND m.role IN ('owner', 'admin')
        );
$$;

REVOKE ALL ON FUNCTION public.is_persona_group_member(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.is_persona_group_manager(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_persona_group_member(uuid) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.is_persona_group_manager(uuid) TO authenticated, service_role;

-- ====================================================================
-- 2. POLICIES. Service-role always bypasses; other policies are
-- per-table and apply to authenticated frontend reads.
-- DROP-then-CREATE so re-running this file replaces existing policies
-- cleanly (CREATE POLICY IF NOT EXISTS doesn't exist in Postgres).
-- ====================================================================

-- ── api_tokens ──────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Users can read own tokens" ON public.api_tokens;
CREATE POLICY "Users can read own tokens" ON public.api_tokens
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can insert own tokens" ON public.api_tokens;
CREATE POLICY "Users can insert own tokens" ON public.api_tokens
    FOR INSERT WITH CHECK (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can update own tokens" ON public.api_tokens;
CREATE POLICY "Users can update own tokens" ON public.api_tokens
    FOR UPDATE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can delete own tokens" ON public.api_tokens;
CREATE POLICY "Users can delete own tokens" ON public.api_tokens
    FOR DELETE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on api_tokens" ON public.api_tokens;
CREATE POLICY "Service role full access on api_tokens" ON public.api_tokens
    FOR ALL USING (auth.role() = 'service_role');

-- ── chat_messages ───────────────────────────────────────────────────
DROP POLICY IF EXISTS "Users can read own messages" ON public.chat_messages;
CREATE POLICY "Users can read own messages" ON public.chat_messages
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on chat_messages" ON public.chat_messages;
CREATE POLICY "Service role full access on chat_messages" ON public.chat_messages
    FOR ALL USING (auth.role() = 'service_role');

-- ── persona_agents ──────────────────────────────────────────────────
DROP POLICY IF EXISTS "Users can read own persona" ON public.persona_agents;
CREATE POLICY "Users can read own persona" ON public.persona_agents
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can update own persona" ON public.persona_agents;
CREATE POLICY "Users can update own persona" ON public.persona_agents
    FOR UPDATE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Public read persona agents" ON public.persona_agents;
CREATE POLICY "Public read persona agents" ON public.persona_agents
    FOR SELECT USING (true);
DROP POLICY IF EXISTS "Service role full access on persona_agents" ON public.persona_agents;
CREATE POLICY "Service role full access on persona_agents" ON public.persona_agents
    FOR ALL USING (auth.role() = 'service_role');

-- ── dm_threads ──────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Users can read own threads" ON public.dm_threads;
CREATE POLICY "Users can read own threads" ON public.dm_threads
    FOR SELECT USING (
        auth.uid()::text = initiator_id
        OR auth.uid()::text = receiver_id
        OR EXISTS (
            SELECT 1 FROM public.persona_agents
             WHERE user_id = auth.uid()
               AND (agent_id = initiator_id OR agent_id = receiver_id)
        )
    );
DROP POLICY IF EXISTS "Users can start threads" ON public.dm_threads;
CREATE POLICY "Users can start threads" ON public.dm_threads
    FOR INSERT WITH CHECK (
        auth.uid()::text = initiator_id
        OR EXISTS (
            SELECT 1 FROM public.persona_agents
             WHERE user_id = auth.uid() AND agent_id = initiator_id
        )
    );
DROP POLICY IF EXISTS "Participants can update threads" ON public.dm_threads;
CREATE POLICY "Participants can update threads" ON public.dm_threads
    FOR UPDATE USING (
        auth.uid()::text = initiator_id
        OR auth.uid()::text = receiver_id
        OR EXISTS (
            SELECT 1 FROM public.persona_agents
             WHERE user_id = auth.uid()
               AND (agent_id = initiator_id OR agent_id = receiver_id)
        )
    );
DROP POLICY IF EXISTS "Service role full access on dm_threads" ON public.dm_threads;
CREATE POLICY "Service role full access on dm_threads" ON public.dm_threads
    FOR ALL USING (auth.role() = 'service_role');

-- ── dm_messages ─────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Users can read messages in non-blocked threads" ON public.dm_messages;
CREATE POLICY "Users can read messages in non-blocked threads" ON public.dm_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.dm_threads t
            WHERE t.id = dm_messages.thread_id
              AND (
                  t.initiator_id = auth.uid()::text
                  OR t.receiver_id = auth.uid()::text
                  OR EXISTS (
                      SELECT 1 FROM public.persona_agents p
                       WHERE p.user_id = auth.uid()
                         AND (p.agent_id = t.initiator_id OR p.agent_id = t.receiver_id)
                  )
              )
              AND t.status NOT IN ('blocked', 'revoked')
        )
    );
DROP POLICY IF EXISTS "Users can send messages in accepted threads" ON public.dm_messages;
CREATE POLICY "Users can send messages in accepted threads" ON public.dm_messages
    FOR INSERT WITH CHECK (
        (auth.uid()::text = sender_id
         OR EXISTS (
             SELECT 1 FROM public.persona_agents
              WHERE user_id = auth.uid() AND agent_id = sender_id
         ))
        AND EXISTS (
            SELECT 1 FROM public.dm_threads t
            WHERE t.id = dm_messages.thread_id
              AND (
                  t.initiator_id = auth.uid()::text
                  OR t.receiver_id = auth.uid()::text
                  OR EXISTS (
                      SELECT 1 FROM public.persona_agents p
                       WHERE p.user_id = auth.uid()
                         AND (p.agent_id = t.initiator_id OR p.agent_id = t.receiver_id)
                  )
              )
              AND t.status NOT IN ('blocked', 'declined', 'revoked')
        )
    );
DROP POLICY IF EXISTS "Service role full access on dm_messages" ON public.dm_messages;
CREATE POLICY "Service role full access on dm_messages" ON public.dm_messages
    FOR ALL USING (auth.role() = 'service_role');

-- ── agent_tasks ─────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Participants can read agent_tasks" ON public.agent_tasks;
CREATE POLICY "Participants can read agent_tasks" ON public.agent_tasks
    FOR SELECT USING (
        auth.uid() = initiator_user_id OR auth.uid() = recipient_user_id
    );
DROP POLICY IF EXISTS "Participants can update agent_tasks" ON public.agent_tasks;
CREATE POLICY "Participants can update agent_tasks" ON public.agent_tasks
    FOR UPDATE USING (
        auth.uid() = initiator_user_id OR auth.uid() = recipient_user_id
    );
DROP POLICY IF EXISTS "Service role full access on agent_tasks" ON public.agent_tasks;
CREATE POLICY "Service role full access on agent_tasks" ON public.agent_tasks
    FOR ALL USING (auth.role() = 'service_role');

-- ── a2a_tasks ───────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Participants can read a2a_tasks" ON public.a2a_tasks;
CREATE POLICY "Participants can read a2a_tasks" ON public.a2a_tasks
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.dm_threads t
            WHERE t.id = a2a_tasks.context_id
              AND (
                  t.initiator_id = auth.uid()::text
                  OR t.receiver_id = auth.uid()::text
                  OR EXISTS (
                      SELECT 1 FROM public.persona_agents p
                       WHERE p.user_id = auth.uid()
                         AND (p.agent_id = t.initiator_id OR p.agent_id = t.receiver_id)
                  )
              )
        )
    );
DROP POLICY IF EXISTS "Service role full access on a2a_tasks" ON public.a2a_tasks;
CREATE POLICY "Service role full access on a2a_tasks" ON public.a2a_tasks
    FOR ALL USING (auth.role() = 'service_role');

-- ── pending_approvals ───────────────────────────────────────────────
DROP POLICY IF EXISTS "Users read own approvals" ON public.pending_approvals;
CREATE POLICY "Users read own approvals" ON public.pending_approvals
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users update own approvals" ON public.pending_approvals;
CREATE POLICY "Users update own approvals" ON public.pending_approvals
    FOR UPDATE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on pending_approvals" ON public.pending_approvals;
CREATE POLICY "Service role full access on pending_approvals" ON public.pending_approvals
    FOR ALL USING (auth.role() = 'service_role');

-- ── telegram_links / telegram_chat_history ──────────────────────────
DROP POLICY IF EXISTS "Users read own telegram link" ON public.telegram_links;
CREATE POLICY "Users read own telegram link" ON public.telegram_links
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users delete own telegram link" ON public.telegram_links;
CREATE POLICY "Users delete own telegram link" ON public.telegram_links
    FOR DELETE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on telegram_links" ON public.telegram_links;
CREATE POLICY "Service role full access on telegram_links" ON public.telegram_links
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Users read own telegram history" ON public.telegram_chat_history;
CREATE POLICY "Users read own telegram history" ON public.telegram_chat_history
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on telegram_chat_history" ON public.telegram_chat_history;
CREATE POLICY "Service role full access on telegram_chat_history" ON public.telegram_chat_history
    FOR ALL USING (auth.role() = 'service_role');

-- ── linkedin_profiles ───────────────────────────────────────────────
DROP POLICY IF EXISTS "Users read own linkedin profile" ON public.linkedin_profiles;
CREATE POLICY "Users read own linkedin profile" ON public.linkedin_profiles
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users delete own linkedin profile" ON public.linkedin_profiles;
CREATE POLICY "Users delete own linkedin profile" ON public.linkedin_profiles
    FOR DELETE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on linkedin_profiles" ON public.linkedin_profiles;
CREATE POLICY "Service role full access on linkedin_profiles" ON public.linkedin_profiles
    FOR ALL USING (auth.role() = 'service_role');

-- ── brief_todos ─────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Users can read own brief todos" ON public.brief_todos;
CREATE POLICY "Users can read own brief todos" ON public.brief_todos
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Group members can read group todos" ON public.brief_todos;
CREATE POLICY "Group members can read group todos" ON public.brief_todos
    FOR SELECT USING (group_id IS NOT NULL AND public.is_persona_group_member(group_id));
DROP POLICY IF EXISTS "Users can update own brief todos" ON public.brief_todos;
CREATE POLICY "Users can update own brief todos" ON public.brief_todos
    FOR UPDATE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users can delete own brief todos" ON public.brief_todos;
CREATE POLICY "Users can delete own brief todos" ON public.brief_todos
    FOR DELETE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role full access on brief_todos" ON public.brief_todos;
CREATE POLICY "Service role full access on brief_todos" ON public.brief_todos
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── outbound_callbacks / callback_results ───────────────────────────
DROP POLICY IF EXISTS "Owner reads outbound_callbacks" ON public.outbound_callbacks;
CREATE POLICY "Owner reads outbound_callbacks" ON public.outbound_callbacks
    FOR SELECT USING (user_id = auth.uid());
DROP POLICY IF EXISTS "Service role full access on outbound_callbacks" ON public.outbound_callbacks;
CREATE POLICY "Service role full access on outbound_callbacks" ON public.outbound_callbacks
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Owner reads callback_results" ON public.callback_results;
CREATE POLICY "Owner reads callback_results" ON public.callback_results
    FOR SELECT USING (user_id = auth.uid());
DROP POLICY IF EXISTS "Owner marks delivered" ON public.callback_results;
CREATE POLICY "Owner marks delivered" ON public.callback_results
    FOR UPDATE USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());
DROP POLICY IF EXISTS "Service role full access on callback_results" ON public.callback_results;
CREATE POLICY "Service role full access on callback_results" ON public.callback_results
    FOR ALL USING (auth.role() = 'service_role');

-- ── persona_groups ──────────────────────────────────────────────────
DROP POLICY IF EXISTS "members read group" ON public.persona_groups;
CREATE POLICY "members read group" ON public.persona_groups
    FOR SELECT USING (public.is_persona_group_member(persona_groups.id));
DROP POLICY IF EXISTS "service role full access on persona_groups" ON public.persona_groups;
CREATE POLICY "service role full access on persona_groups" ON public.persona_groups
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── persona_group_members ───────────────────────────────────────────
DROP POLICY IF EXISTS "members read roster" ON public.persona_group_members;
CREATE POLICY "members read roster" ON public.persona_group_members
    FOR SELECT USING (public.is_persona_group_member(persona_group_members.group_id));
DROP POLICY IF EXISTS "service role full access on persona_group_members" ON public.persona_group_members;
CREATE POLICY "service role full access on persona_group_members" ON public.persona_group_members
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── persona_group_messages ──────────────────────────────────────────
DROP POLICY IF EXISTS "members read messages" ON public.persona_group_messages;
CREATE POLICY "members read messages" ON public.persona_group_messages
    FOR SELECT USING (public.is_persona_group_member(persona_group_messages.group_id));
DROP POLICY IF EXISTS "service role full access on persona_group_messages" ON public.persona_group_messages;
CREATE POLICY "service role full access on persona_group_messages" ON public.persona_group_messages
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── persona_group_constraints ──────────────────────────────────────
DROP POLICY IF EXISTS "members read group constraints" ON public.persona_group_constraints;
CREATE POLICY "members read group constraints" ON public.persona_group_constraints
    FOR SELECT USING (public.is_persona_group_member(persona_group_constraints.group_id));
DROP POLICY IF EXISTS "service role full access on persona_group_constraints" ON public.persona_group_constraints;
CREATE POLICY "service role full access on persona_group_constraints" ON public.persona_group_constraints
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── persona_group_audit_events ──────────────────────────────────────
DROP POLICY IF EXISTS "affected user reads own audit events" ON public.persona_group_audit_events;
CREATE POLICY "affected user reads own audit events" ON public.persona_group_audit_events
    FOR SELECT USING (auth.uid() = affected_user_id);
DROP POLICY IF EXISTS "owner reads group audit events" ON public.persona_group_audit_events;
CREATE POLICY "owner reads group audit events" ON public.persona_group_audit_events
    FOR SELECT USING (public.is_persona_group_manager(persona_group_audit_events.group_id));
DROP POLICY IF EXISTS "service role full access on persona_group_audit_events" ON public.persona_group_audit_events;
CREATE POLICY "service role full access on persona_group_audit_events" ON public.persona_group_audit_events
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Clean up the older two-argument helper shape if this file was applied
-- from an intermediate local branch. The one-argument helpers above read
-- auth.uid() internally, so direct RPC calls cannot test another user's
-- membership.
DROP FUNCTION IF EXISTS public.is_persona_group_member(uuid, uuid);
DROP FUNCTION IF EXISTS public.is_persona_group_manager(uuid, uuid);

-- ====================================================================
-- 3. PARTIAL INDEXES Prisma can't express (filter clauses, NULL ordering).
-- ====================================================================
CREATE INDEX IF NOT EXISTS a2a_tasks_state_idle_idx
    ON public.a2a_tasks (state, idle_until)
    WHERE state IN ('input-required', 'auth-required');

CREATE INDEX IF NOT EXISTS outbound_callbacks_peer_task_idx
    ON public.outbound_callbacks (peer_agent_id, peer_task_id)
    WHERE peer_task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS outbound_callbacks_expires_idx
    ON public.outbound_callbacks (expires_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS persona_groups_join_domain_idx
    ON public.persona_groups (join_domain)
    WHERE join_domain IS NOT NULL AND archived_at IS NULL;

CREATE INDEX IF NOT EXISTS persona_group_constraints_group_idx
    ON public.persona_group_constraints (group_id, archived_at NULLS FIRST, created_at DESC);

-- ====================================================================
-- 4. SUPABASE REALTIME PUBLICATION
-- Tables the frontend subscribes to for live updates.
-- ====================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime'
    ) THEN
        CREATE PUBLICATION supabase_realtime;
    END IF;
END $$;

-- ALTER PUBLICATION ... ADD TABLE is idempotent via the pg_publication_tables check.
DO $$
DECLARE
    t TEXT;
    tables TEXT[] := ARRAY[
        'dm_threads',
        'dm_messages',
        'agent_tasks',
        'a2a_tasks',
        'pending_approvals',
        'callback_results',
        'persona_group_messages'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_publication_tables
             WHERE pubname = 'supabase_realtime'
               AND schemaname = 'public'
               AND tablename = t
        ) THEN
            EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE public.%I', t);
        END IF;
    END LOOP;
END $$;
