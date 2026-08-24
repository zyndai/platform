-- Migration: group-assignable todos
--
-- Lets a todo originate from a Persona Group @mention instead of the
-- user's own brief. `group_id` records which group the assignment came
-- from; `assigned_by_user_id` records who assigned it. Both nullable —
-- personal todos (the existing default) leave them null and are
-- unaffected. See backend/mcp/tools/brief.py's add_todo and
-- backend/agent/group_dispatch.py for the write path.

ALTER TABLE brief_todos
  ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES persona_groups(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS assigned_by_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS brief_todos_group_idx ON brief_todos (group_id);
