-- owner: cards
-- Search functions for cards-api (services/cards-api/services/search.py calls
-- them via sb.rpc), and access lockdown for the cards tables.
--
-- Bodies are verbatim from xmfj (2026-09-26). One change: `SET search_path`,
-- because `vector` and its <=> operator now live in the `extensions` schema.
CREATE OR REPLACE FUNCTION public.match_cards(query_embedding extensions.vector, match_count integer DEFAULT 200)
 RETURNS TABLE(id text, handle text, card jsonb, similarity double precision)
 LANGUAGE sql
 STABLE
 SET search_path TO 'public', 'extensions'
AS $function$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
   order by c.embedding <=> query_embedding
   limit match_count;
$function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION public.search_cards_fts(q text, match_count integer DEFAULT 200)
 RETURNS TABLE(id text, handle text, card jsonb, rank real)
 LANGUAGE sql
 STABLE
 SET search_path TO 'public', 'extensions'
AS $function$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from agent_profile_cards c
   where c.status = 'published'
     and c.search_tsv @@ websearch_to_tsquery('english', q)
   order by 4 desc
   limit match_count;
$function$;
--> statement-breakpoint
-- Only cards-api (service role) may call them. Supabase's default privileges
-- would otherwise expose them as public RPCs to the anon key.
REVOKE EXECUTE ON FUNCTION public.match_cards(extensions.vector, integer) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.search_cards_fts(text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.match_cards(extensions.vector, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_cards_fts(text, integer) TO service_role;
--> statement-breakpoint
-- Same posture as xmfj: the browser API roles get no table privileges at all
-- (RLS already denies them; this is defence in depth).
REVOKE ALL ON TABLE public.agent_profile_cards, public.x_accounts, public.x_conversations, public.x_mentions
  FROM anon, authenticated;
