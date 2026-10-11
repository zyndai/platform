-- owner: cards
-- S03: point the search RPCs at the new stored `claimed` flag (0006) instead of
-- `owner_email IS NOT NULL` — same behaviour, one source of truth. Signatures
-- and the include_unclaimed DEFAULT false semantics are unchanged.
-- Rollback: CREATE OR REPLACE both functions with `owner_email IS NOT NULL`.
CREATE OR REPLACE FUNCTION cards.match_cards(query_embedding extensions.vector, match_count integer DEFAULT 200, include_unclaimed boolean DEFAULT false)
 RETURNS TABLE(id text, handle text, card jsonb, similarity double precision)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
     and (include_unclaimed or c.claimed)
   order by c.embedding <=> query_embedding
   limit match_count;
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.search_cards_fts(q text, match_count integer DEFAULT 200, include_unclaimed boolean DEFAULT false)
 RETURNS TABLE(id text, handle text, card jsonb, rank real)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from agent_profile_cards c
   where c.status = 'published'
     and c.search_tsv @@ websearch_to_tsquery('english', q)
     and (include_unclaimed or c.claimed)
   order by 4 desc
   limit match_count;
$function$;