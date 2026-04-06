-- ================================================================
-- Zynd AI — Direct Messaging & P2P Realtime Architecture
-- Run this in the Supabase SQL Editor
-- ================================================================

-- 1. Create the Threads table (tracks the connection between two users)
CREATE TABLE IF NOT EXISTS dm_threads (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    initiator_id  UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    receiver_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending', -- Can be: 'pending', 'accepted', 'blocked'
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(initiator_id, receiver_id)
);

-- 2. Create the actual Messages table
CREATE TABLE IF NOT EXISTS dm_messages (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    thread_id     UUID NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
    sender_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- ================================================================
-- ROW LEVEL SECURITY (RLS) - The Secret to Safe Messaging
-- ================================================================

ALTER TABLE dm_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE dm_messages ENABLE ROW LEVEL SECURITY;

-- ── Threads Policies ── --
-- Users can only see threads they are participants in
CREATE POLICY "Users can read own threads" ON dm_threads
    FOR SELECT USING (auth.uid() = initiator_id OR auth.uid() = receiver_id);

-- Anyone can initiate a thread to message someone else
CREATE POLICY "Users can start threads" ON dm_threads
    FOR INSERT WITH CHECK (auth.uid() = initiator_id);

-- ONLY the receiver of the message request can accept or block the thread
CREATE POLICY "Receiver can accept or block threads" ON dm_threads
    FOR UPDATE USING (auth.uid() = receiver_id);


-- ── Messages Policies (Where the WebSockets filter happens) ── --
-- Users can only read messages in their threads IF the thread status is NOT blocked
CREATE POLICY "Users can read messages in non-blocked threads" ON dm_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM dm_threads t 
            WHERE t.id = dm_messages.thread_id 
              AND (t.initiator_id = auth.uid() OR t.receiver_id = auth.uid())
              AND t.status != 'blocked'
        )
    );

-- Users can only SEND messages if the thread is not blocked by the other user
CREATE POLICY "Users can send messages in non-blocked threads" ON dm_messages
    FOR INSERT WITH CHECK (
        auth.uid() = sender_id AND
        EXISTS (
            SELECT 1 FROM dm_threads t 
            WHERE t.id = dm_messages.thread_id 
              AND (t.initiator_id = auth.uid() OR t.receiver_id = auth.uid())
              AND t.status != 'blocked'
        )
    );

-- ================================================================
-- REALTIME TRIGGER
-- This allows Supabase WebSockets to stream incoming messages live
-- ================================================================
-- Add the dm_messages table to the realtime publication
BEGIN;
  DROP PUBLICATION IF EXISTS supabase_realtime;
  CREATE PUBLICATION supabase_realtime;
COMMIT;
ALTER PUBLICATION supabase_realtime ADD TABLE dm_messages;
