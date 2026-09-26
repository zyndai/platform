-- owner: cards
-- The cards schema, and what the cards tables (0001) need before they exist.
-- Cards moves here from the dashboard's Supabase project (xmfj), where its
-- tables sat in `public`.
CREATE SCHEMA "cards";
--> statement-breakpoint
-- Service role only. cards-api is the sole reader/writer (cards-web goes
-- through it), so anon/authenticated get nothing in this schema. Supabase's
-- default grants only cover `public`, so grants are explicit here.
GRANT USAGE ON SCHEMA cards TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA cards GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA cards GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA cards REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cards GRANT EXECUTE ON FUNCTIONS TO service_role;
--> statement-breakpoint
-- pgvector, for agent_profile_cards.embedding. In `extensions`, Supabase's
-- default (xmfj had it in public).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
--> statement-breakpoint
-- Verbatim from xmfj (2026-09-26), moved into the cards schema. IMMUTABLE
-- because the generated column agent_profile_cards.search_tsv calls it.
CREATE OR REPLACE FUNCTION cards.skill_names(card jsonb)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select coalesce(string_agg(s->>'name', ' ' order by s->>'name'), '')
  from jsonb_array_elements(coalesce(card->'skills', '[]'::jsonb)) s
$function$;
