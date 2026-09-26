-- owner: cards
-- Prerequisites for the cards tables (0003), which move here from the
-- dashboard's Supabase project (xmfj). Must run before 0003: the generated
-- search_tsv column calls skill_names(), and the embedding column is a vector.
--
-- vector goes in `extensions` (Supabase's default; xmfj had it in public).
-- Supabase's search_path includes `extensions`, so unqualified `vector` resolves.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
--> statement-breakpoint
-- Verbatim from xmfj (2026-09-26). IMMUTABLE because a generated column uses it.
CREATE OR REPLACE FUNCTION public.skill_names(card jsonb)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select coalesce(string_agg(s->>'name', ' ' order by s->>'name'), '')
  from jsonb_array_elements(coalesce(card->'skills', '[]'::jsonb)) s
$function$;
