-- Semantic search: pgvector + embedding column for Agent Profile Cards.

create extension if not exists vector;

alter table agent_profile_cards
  add column if not exists embedding vector(1536);

create index if not exists agent_profile_cards_embedding_hnsw_idx
  on agent_profile_cards using hnsw (embedding vector_cosine_ops);
