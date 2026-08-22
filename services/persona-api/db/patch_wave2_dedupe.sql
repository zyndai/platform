-- Wave 2 hardening (additive only):
--
-- 1. brief_todos: dedupe by (user_id, title). The watcher and /extract
--    deduped via read-then-insert with no DB uniqueness, so concurrent
--    extractions (double-click Refresh, or a poll racing an extract, or
--    prod+dev both watching) inserted duplicate rows. Collapse existing
--    dupes, then enforce uniqueness; inserts use ON CONFLICT DO NOTHING.
--
-- 2. agent_tasks: at most ONE open meeting proposal per thread. The old
--    check-then-insert in create_proposal let two racing calls create two
--    tickets for the same thread.

DELETE FROM brief_todos a
USING brief_todos b
WHERE a.user_id = b.user_id
  AND a.title = b.title
  AND a.done = b.done
  AND a.id > b.id;

CREATE UNIQUE INDEX IF NOT EXISTS brief_todos_user_title_uniq
    ON brief_todos (user_id, title)
    WHERE done = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS agent_tasks_one_open_proposal
    ON agent_tasks (thread_id)
    WHERE status IN ('proposed', 'countered', 'accepted');