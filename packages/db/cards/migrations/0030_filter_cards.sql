-- owner: cards
-- People search Phase 1.6: filter cards in the database instead of paging every published card
-- into cards-api. A search with a role, place or skill used to read the whole corpus (card JSON
-- and 1536-float embedding each) and filter it in Python; this returns only the cards that could
-- pass, with their similarity already computed, so the transfer is the survivors and no vectors.
--
-- It is a SUPERSET filter by design: cards-api still applies its exact rules (whole-word skill
-- matching, role synonyms, country widening) to what comes back, so this never has to reproduce
-- them, only to never drop a card they would keep. To be safe about that, matching is by
-- substring on lower-cased text with everything but letters, digits, + and # removed, and the
-- caller sends every spelling a rule could accept (synonyms, aliases, a country's cities).
--   p_role, p_skills  jsonb array of groups; each group is an array of fragments. A card needs
--                     at least one fragment of EVERY group, anywhere in its card JSON.
--   p_location        text[] of fragments; at least one must be in identity.location.
--   query_embedding   when given, similarity = 1 - cosine distance (NULL for a card without a
--                     vector); results are ordered by it.
-- Additive: a new function, nothing existing changes. cards-api falls back to the old scan when
-- the function is missing, so it can deploy in either order.
-- Rollback: DROP FUNCTION cards.filter_cards(jsonb, text[], jsonb, extensions.vector, boolean, integer);
CREATE OR REPLACE FUNCTION cards.filter_cards(
  p_role jsonb DEFAULT '[]'::jsonb,
  p_location text[] DEFAULT '{}'::text[],
  p_skills jsonb DEFAULT '[]'::jsonb,
  query_embedding extensions.vector DEFAULT NULL,
  include_unclaimed boolean DEFAULT false,
  match_count integer DEFAULT 1000)
 RETURNS TABLE(id text, handle text, card jsonb, similarity double precision, claimed boolean)
 LANGUAGE sql
 STABLE
 SET search_path TO 'cards', 'extensions'
AS $function$
  with flat as (
    select c.id, c.handle, c.card, c.claimed, c.embedding,
           regexp_replace(lower(c.card::text), '[^a-z0-9+#]', '', 'g') as everything,
           regexp_replace(lower(coalesce(c.card->'identity'->>'location', '')), '[^a-z0-9+#]', '', 'g') as place
      from agent_profile_cards c
     where c.status = 'published' and (include_unclaimed or c.claimed)
  )
  select f.id, f.handle, f.card,
         case when query_embedding is not null and f.embedding is not null
              then 1 - (f.embedding <=> query_embedding) end,
         f.claimed
    from flat f
   where not exists (
           select 1 from jsonb_array_elements(p_role) g
            where jsonb_array_length(g) > 0 and not exists (
                  select 1 from jsonb_array_elements_text(g) frag where position(frag in f.everything) > 0))
     and not exists (
           select 1 from jsonb_array_elements(p_skills) g
            where jsonb_array_length(g) > 0 and not exists (
                  select 1 from jsonb_array_elements_text(g) frag where position(frag in f.everything) > 0))
     and (coalesce(cardinality(p_location), 0) = 0
          or exists (select 1 from unnest(p_location) frag where position(frag in f.place) > 0))
   order by (case when query_embedding is not null and f.embedding is not null
                  then f.embedding <=> query_embedding end) nulls last, f.id
   limit match_count;
$function$;
