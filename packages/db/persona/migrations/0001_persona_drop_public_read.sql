-- owner: persona
-- Stop exposing every persona row to the anon key. The dropped policy was
-- `for select using (true)`; the owner still reads their own row through
-- "Users can read own persona", and the backends use the service role.
-- Every RLS subquery on persona_agents (dm_threads, dm_messages, a2a_tasks
-- policies) filters user_id = auth.uid(), which the owner policy allows.
-- Rollback: create policy "Public read persona agents" on persona_agents for select using (true);
DROP POLICY "Public read persona agents" ON "persona_agents" CASCADE;
