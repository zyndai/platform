-- owner: cards
-- S03: optional include_unclaimed on search RPCs (old 2-arg functions stay)
-- plus a takedown queue. Expand-only.
-- Rollback:
--   DROP FUNCTION IF EXISTS cards.match_cards(extensions.vector, integer, boolean);
--   DROP FUNCTION IF EXISTS cards.search_cards_fts(text, integer, boolean);
--   DROP TABLE IF EXISTS cards.takedown_requests;

CREATE OR REPLACE FUNCTION cards.match_cards(
  query_embedding extensions.vector,
  match_count integer DEFAULT 200,
  include_unclaimed boolean DEFAULT false
)
 RETURNS TABLE(id text, handle text, card jsonb, similarity double precision)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
     and (include_unclaimed or c.owner_email is not null)
   order by c.embedding <=> query_embedding
   limit match_count;
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.search_cards_fts(
  q text,
  match_count integer DEFAULT 200,
  include_unclaimed boolean DEFAULT false
)
 RETURNS TABLE(id text, handle text, card jsonb, rank real)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from agent_profile_cards c
   where c.status = 'published'
     and c.search_tsv @@ websearch_to_tsquery('english', q)
     and (include_unclaimed or c.owner_email is not null)
   order by 4 desc
   limit match_count;
$function$;
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS cards.takedown_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  handle text NOT NULL,
  requester_user_id text,
  note text,
  status text NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE cards.takedown_requests ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY "service role full access on takedown_requests" ON cards.takedown_requests AS PERMISSIVE FOR ALL TO service_role USING (true) WITH CHECK (true);
