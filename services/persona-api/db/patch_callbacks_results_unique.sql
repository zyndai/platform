-- Additive: make "one recorded result per callback" atomic across the
-- TWO backend processes (prod + dev) that share this Supabase project.
-- record_result's old SELECT-then-INSERT let the prod push-handler and the
-- dev poller both insert a row for the same rejected task — two different
-- row ids, two "Update from X (rejected)" banners in the chat.
--
-- 1. Collapse any pre-existing duplicates (keep the earliest row).
-- 2. Add the UNIQUE constraint that makes the upsert race-free.

DELETE FROM callback_results a
USING callback_results b
WHERE a.callback_id = b.callback_id
  AND a.id > b.id;

ALTER TABLE callback_results
    ADD CONSTRAINT callback_results_callback_id_key UNIQUE (callback_id);

-- Additive: terminal outcome on the parent callback so the frontend can
-- render "✗ Rejected"/"✗ Failed" instead of "✓ done" for failed calls.
ALTER TABLE outbound_callbacks
    ADD COLUMN IF NOT EXISTS terminal_state TEXT;