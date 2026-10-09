-- owner: cards
-- S03: the two search RPCs get an include_unclaimed flag so agent callers
-- (cards-api /ask, /v1/agents/search) default to claimed cards only. The old
-- two-argument signature stays working via DEFAULT false — but note the
-- default deliberately excludes unclaimed cards; the website's own directory
-- UI passes include_unclaimed => true.
-- Rollback: recreate without the flag and the owner filter:
--   CREATE OR REPLACE FUNCTION cards.match_cards(query_embedding extensions.vector, match_count integer DEFAULT 200)
--    RETURNS TABLE(id text, handle text, card jsonb, similarity double precision)
--    LANGUAGE sql STABLE SET search_path TO 'cards', 'extensions'
--   AS $function$
--     select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
--       from agent_profile_cards c
--      where c.status = 'published' and c.embedding is not null
--      order by c.embedding <=> query_embedding
--      limit match_count;
--   $function$;
--   CREATE OR REPLACE FUNCTION cards.search_cards_fts(q text, match_count integer DEFAULT 200)
--    RETURNS TABLE(id text, handle text, card jsonb, rank real)
--    LANGUAGE sql STABLE SET search_path TO 'cards', 'extensions'
--   AS $function$
--     select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
--       from agent_profile_cards c
--      where c.status = 'published'
--        and c.search_tsv @@ websearch_to_tsquery('english', q)
--      order by 4 desc
--      limit match_count;
--   $function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.match_cards(query_embedding extensions.vector, match_count integer DEFAULT 200, include_unclaimed boolean DEFAULT false)
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
     and (include_unclaimed or c.owner_email is not null)
   order by 4 desc
   limit match_count;
$function$;