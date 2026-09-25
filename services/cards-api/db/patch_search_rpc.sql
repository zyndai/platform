-- Search candidates in SQL so the HNSW / GIN indexes do the work.
--
-- services/search.py used to load up to 1000 published cards per query and
-- rank them in Python: slow, and card #1001 could never be found. These two
-- functions return the top matches by vector similarity and by full-text rank;
-- the Python scorer then re-ranks that candidate set.
--
-- Safe to apply before or after the code deploy: search.py falls back to a
-- paged scan if the functions are missing.

create or replace function match_cards(query_embedding vector(1536), match_count int default 200)
returns table (id text, handle text, card jsonb, similarity double precision)
language sql stable as $$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
   order by c.embedding <=> query_embedding
   limit match_count;
$$;

create or replace function search_cards_fts(q text, match_count int default 200)
returns table (id text, handle text, card jsonb, rank real)
language sql stable as $$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from agent_profile_cards c
   where c.status = 'published'
     and c.search_tsv @@ websearch_to_tsquery('english', q)
   order by 4 desc
   limit match_count;
$$;
