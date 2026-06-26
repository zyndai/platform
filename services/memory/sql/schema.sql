-- ZYND schema — Postgres 16 + pgvector. Six tables, no other database at MVP.
-- Idempotent: safe to re-apply. See architecture brief §3.

CREATE EXTENSION IF NOT EXISTS vector;

-- §3.1 users
CREATE TABLE IF NOT EXISTS users (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email          text UNIQUE NOT NULL,
  display_name   text,
  password_hash  text,                              -- PBKDF2; null for OAuth-only/legacy rows
  privacy_mode   boolean NOT NULL DEFAULT false,   -- if true, route to local extraction
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_active_at timestamptz
);
-- Idempotent migration for already-created databases.
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash text;

-- §3.2 trace_chunks — append-only, NEVER mutate. Ground truth.
CREATE TABLE IF NOT EXISTS trace_chunks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id),
  source_system   text NOT NULL,            -- chatgpt | claude | codex | import
  raw_text        text NOT NULL,            -- user turn content only (never assistant)
  conversation_id text,
  turn_start      int,
  turn_end        int,
  content_hash    text NOT NULL,            -- SHA-256(user_id + chunk_text) for dedup
  embedding       vector(1536),             -- text-embedding-3-small output; null until embed worker runs
  observed_at     timestamptz,             -- when conversation happened
  ingested_at     timestamptz NOT NULL DEFAULT now()
);

-- §3.3 entities — user-scoped. No global entity table.
CREATE TABLE IF NOT EXISTS entities (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id),
  canonical_name text NOT NULL,             -- normalized form e.g. "Rust async runtimes"
  entity_type    text NOT NULL,             -- taxonomy enum, brief §2
  aliases        text[] NOT NULL DEFAULT '{}',
  place_meta     jsonb,                     -- only for place_physical: {city,country,lat,lng,tz}
  embedding      vector(1536),             -- embedding of canonical_name
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- §3.4 assertions — the core table.
CREATE TABLE IF NOT EXISTS assertions (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           uuid NOT NULL REFERENCES users(id),
  subject_entity_id uuid REFERENCES entities(id),   -- always the user (self) for MVP
  predicate         text NOT NULL,                  -- allowed list, brief §4
  object_entity_id  uuid REFERENCES entities(id),   -- use this OR object_literal
  object_literal    text,
  -- confidence capped at 0.97: the system must never treat any assertion as certain (§14)
  confidence        real NOT NULL CHECK (confidence >= 0.0 AND confidence <= 0.97),
  source_system     text NOT NULL,                  -- chatgpt | claude | user_confirmed | import
  trace_chunk_id    uuid REFERENCES trace_chunks(id),
  decay_fn          text NOT NULL DEFAULT 'none',    -- e.g. exponential(halflife=30d) | none
  version           int NOT NULL DEFAULT 1,          -- increments on each Bayesian update
  observed_at       timestamptz,
  extracted_at      timestamptz NOT NULL DEFAULT now(),
  valid_until       timestamptz                     -- set by decay job when confidence < 0.1
);

-- §3.5 assertion_history — append-only audit log.
CREATE TABLE IF NOT EXISTS assertion_history (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assertion_id    uuid NOT NULL REFERENCES assertions(id),
  prev_confidence real,
  new_confidence  real,
  change_reason   text NOT NULL,   -- new_evidence | decay | contradiction | user_confirmed | user_deleted
  changed_at      timestamptz NOT NULL DEFAULT now()
);

-- §3.6 user_embeddings — materialized matching layer.
CREATE TABLE IF NOT EXISTS user_embeddings (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id),
  cluster_type    text NOT NULL,   -- intent_cluster | skill_cluster | belief_cluster | concept_cluster | full_context
  embedding       vector(1536),    -- confidence-weighted average of assertion entity embeddings
  computed_at     timestamptz NOT NULL DEFAULT now(),
  assertion_count int NOT NULL DEFAULT 0
);

-- §3.7 indexes -------------------------------------------------------------

-- ANN matching index (HNSW for approximate nearest neighbor over cosine distance)
CREATE INDEX IF NOT EXISTS user_embeddings_hnsw
  ON user_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Primary assertion lookup pattern
CREATE INDEX IF NOT EXISTS assertions_user_pred_conf
  ON assertions (user_id, predicate, confidence DESC);

-- Decay job: find assertions expiring soon
CREATE INDEX IF NOT EXISTS assertions_valid_until
  ON assertions (valid_until) WHERE valid_until IS NOT NULL;

-- Dedup check on ingest
CREATE UNIQUE INDEX IF NOT EXISTS trace_chunks_user_hash
  ON trace_chunks (user_id, content_hash);

-- Entity resolution by name within user scope
CREATE INDEX IF NOT EXISTS entities_user_type_name
  ON entities (user_id, entity_type, canonical_name);

-- Matching layer unique constraint
CREATE UNIQUE INDEX IF NOT EXISTS user_embeddings_user_cluster
  ON user_embeddings (user_id, cluster_type);
