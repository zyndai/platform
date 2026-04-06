-- Run this in your Supabase SQL Editor to fix the 400 Bad Request Error!

-- 1. Wipe the old restrictive tables
DROP TABLE IF EXISTS dm_messages CASCADE;
DROP TABLE IF EXISTS dm_threads CASCADE;

-- 2. Recreate them using TEXT instead of restricted UUIDs, so it can accept Network DIDs (did:polygon:...)
CREATE TABLE IF NOT EXISTS dm_threads (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    initiator_id  TEXT NOT NULL,  -- Replaced UUID with TEXT
    receiver_id   TEXT NOT NULL,  -- Replaced UUID with TEXT
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(initiator_id, receiver_id)
);

CREATE TABLE IF NOT EXISTS dm_messages (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    thread_id     UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    sender_id     TEXT NOT NULL,  -- Replaced UUID with TEXT 
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE dm_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE dm_messages ENABLE ROW LEVEL SECURITY;

-- ── Threads Policies ── --
-- Notice we cast auth.uid() to text (::text) to match the new columns
CREATE POLICY "Users can read own threads" ON dm_threads
    FOR SELECT USING (auth.uid()::text = initiator_id OR auth.uid()::text = receiver_id);

CREATE POLICY "Users can start threads" ON dm_threads
    FOR INSERT WITH CHECK (auth.uid()::text = initiator_id);

CREATE POLICY "Receiver can accept or block threads" ON dm_threads
    FOR UPDATE USING (auth.uid()::text = receiver_id);

-- ── Messages Policies ── --
CREATE POLICY "Users can read messages in non-blocked threads" ON dm_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM dm_threads t 
            WHERE t.id = dm_messages.thread_id 
              AND (t.initiator_id = auth.uid()::text OR t.receiver_id = auth.uid()::text)
              AND t.status != 'blocked'
        )
    );

CREATE POLICY "Users can send messages in non-blocked threads" ON dm_messages
    FOR INSERT WITH CHECK (
        auth.uid()::text = sender_id AND
        EXISTS (
            SELECT 1 FROM dm_threads t 
            WHERE t.id = dm_messages.thread_id 
              AND (t.initiator_id = auth.uid()::text OR t.receiver_id = auth.uid()::text)
              AND t.status != 'blocked'
        )
    );

-- ── Realtime Setup ── --
BEGIN;
  DROP PUBLICATION IF EXISTS supabase_realtime;
  CREATE PUBLICATION supabase_realtime;
COMMIT;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_messages;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_threads;
