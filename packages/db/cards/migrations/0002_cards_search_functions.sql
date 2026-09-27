-- owner: cards
-- Search functions cards-api calls over PostgREST RPC
-- (services/cards-api/services/search.py). Bodies verbatim from xmfj
-- (2026-09-26), now in the cards schema, with an explicit search_path because
-- `vector` and its <=> operator live in `extensions`.
CREATE OR REPLACE FUNCTION cards.match_cards(query_embedding extensions.vector, match_count integer DEFAULT 200)
 RETURNS TABLE(id text, handle text, card jsonb, similarity double precision)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
   order by c.embedding <=> query_embedding
   limit match_count;
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.search_cards_fts(q text, match_count integer DEFAULT 200)
 RETURNS TABLE(id text, handle text, card jsonb, rank real)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from agent_profile_cards c
   where c.status = 'published'
     and c.search_tsv @@ websearch_to_tsquery('english', q)
   order by 4 desc
   limit match_count;
$function$;
