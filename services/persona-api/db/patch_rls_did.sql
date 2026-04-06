-- Run this in your Supabase SQL Editor!

-- 1. Create a crucial mapping table to link local User UUIDs to external Agent DIDs
CREATE TABLE IF NOT EXISTS persona_dids (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    did TEXT NOT NULL UNIQUE
);

ALTER TABLE persona_dids ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Full access to own dids" ON persona_dids FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Public read dids" ON persona_dids FOR SELECT USING (true);


-- 2. Drop and Recreate RLS on dm_threads to support DID mapping lookups natively!
DROP POLICY IF EXISTS "Users can read own threads" ON dm_threads;
CREATE POLICY "Users can read own threads" ON dm_threads
    FOR SELECT USING (
        auth.uid()::text = initiator_id 
        OR auth.uid()::text = receiver_id
        OR EXISTS (SELECT 1 FROM persona_dids WHERE user_id = auth.uid() AND (did = initiator_id OR did = receiver_id))
    );

DROP POLICY IF EXISTS "Users can start threads" ON dm_threads;
CREATE POLICY "Users can start threads" ON dm_threads
    FOR INSERT WITH CHECK (
        auth.uid()::text = initiator_id
        OR EXISTS (SELECT 1 FROM persona_dids WHERE user_id = auth.uid() AND did = initiator_id)
    );

DROP POLICY IF EXISTS "Receiver can accept or block threads" ON dm_threads;
CREATE POLICY "Receiver can accept or block threads" ON dm_threads
    FOR UPDATE USING (
        auth.uid()::text = receiver_id
        OR EXISTS (SELECT 1 FROM persona_dids WHERE user_id = auth.uid() AND did = receiver_id)
    );

-- 3. Drop and Recreate RLS on dm_messages
DROP POLICY IF EXISTS "Users can read messages in non-blocked threads" ON dm_messages;
CREATE POLICY "Users can read messages in non-blocked threads" ON dm_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM dm_threads t 
            WHERE t.id = dm_messages.thread_id 
              AND (
                  t.initiator_id = auth.uid()::text OR t.receiver_id = auth.uid()::text
                  OR EXISTS (SELECT 1 FROM persona_dids p WHERE p.user_id = auth.uid() AND (p.did = t.initiator_id OR p.did = t.receiver_id))
              )
              AND t.status != 'blocked'
        )
    );

DROP POLICY IF EXISTS "Users can send messages in non-blocked threads" ON dm_messages;
CREATE POLICY "Users can send messages in non-blocked threads" ON dm_messages
    FOR INSERT WITH CHECK (
        (auth.uid()::text = sender_id OR EXISTS(SELECT 1 FROM persona_dids WHERE user_id = auth.uid() AND did = sender_id))
        AND
        EXISTS (
            SELECT 1 FROM dm_threads t 
            WHERE t.id = dm_messages.thread_id 
              AND (
                  t.initiator_id = auth.uid()::text OR t.receiver_id = auth.uid()::text
                  OR EXISTS (SELECT 1 FROM persona_dids p WHERE p.user_id = auth.uid() AND (p.did = t.initiator_id OR p.did = t.receiver_id))
              )
              AND t.status != 'blocked'
        )
    );
