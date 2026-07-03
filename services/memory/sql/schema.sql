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
  -- confidence capped at 0.97: the system must never treat any assertion as certain (§14).
  -- double precision (not real): float4 rounds 0.97 up past the check bound.
  confidence        double precision NOT NULL CHECK (confidence >= 0.0 AND confidence <= 0.97),
  source_system     text NOT NULL,                  -- chatgpt | claude | user_confirmed | import
  trace_chunk_id    uuid REFERENCES trace_chunks(id),
  decay_fn          text NOT NULL DEFAULT 'none',    -- e.g. exponential(halflife=30d) | none
  version           int NOT NULL DEFAULT 1,          -- increments on each Bayesian update
  observed_at       timestamptz,
  extracted_at      timestamptz NOT NULL DEFAULT now(),
  valid_until       timestamptz                     -- set by decay job when confidence < 0.1
);

-- v2 — memory vs findability split. Private memory is automatic (all predicates);
-- only is_public=true rows in FINDABILITY_PREDICATES are used for matching/discovery.
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'inferred';  -- inferred | declared | system
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false; -- approved onto the public findability card
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS approved_at timestamptz;
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS gate text;                                -- health | politics | immigration | null

-- persona integration: link a ZYND user to their Supabase identity + persona agent.
ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_user_id text;   -- Supabase auth.users.id (keys the persona network)
ALTER TABLE users ADD COLUMN IF NOT EXISTS persona_agent_id text;   -- zns:<hash> from agent-persona

-- sign-out / disconnect: tokens issued before this watermark are rejected (see services/sessions).
ALTER TABLE users ADD COLUMN IF NOT EXISTS tokens_revoked_at timestamptz;

-- public social links, synced from the persona profile (shown with matches). {} = none.
ALTER TABLE users ADD COLUMN IF NOT EXISTS socials jsonb NOT NULL DEFAULT '{}'::jsonb;

-- §3.5 assertion_history — append-only audit log.
CREATE TABLE IF NOT EXISTS assertion_history (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assertion_id    uuid NOT NULL REFERENCES assertions(id),
  prev_confidence double precision,
  new_confidence  double precision,
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

-- Idempotent migration: float4 -> float8 for confidence (no-op if already double).
ALTER TABLE assertions        ALTER COLUMN confidence     TYPE double precision;
ALTER TABLE assertion_history ALTER COLUMN prev_confidence TYPE double precision;
ALTER TABLE assertion_history ALTER COLUMN new_confidence  TYPE double precision;

-- Shareable HTML / Markdown pages the GPT/agent hosts on the user's behalf.
-- Slug is an unguessable token; pages are server-rendered at
-- {public_base_url}/pages/{slug}. Cascade-deletes with the owning user.
CREATE TABLE IF NOT EXISTS published_pages (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slug        text NOT NULL UNIQUE,
  title       text NOT NULL DEFAULT 'Untitled page',
  format      text NOT NULL DEFAULT 'html' CHECK (format IN ('html','markdown')),
  content     text NOT NULL,
  visibility  text NOT NULL DEFAULT 'unlisted' CHECK (visibility IN ('public','unlisted','private')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS published_pages_slug_idx ON published_pages (slug);
CREATE INDEX IF NOT EXISTS published_pages_user_idx ON published_pages (user_id, created_at DESC);

-- OAuth 2.1 Dynamic Client Registration (DCR) — used by Claude Desktop/Web/Mobile
-- connectors. Clients register themselves; no manual per-user client setup needed.
CREATE TABLE IF NOT EXISTS oauth_clients (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id              text NOT NULL UNIQUE,
  client_secret          text,                              -- null for public clients (PKCE)
  allowed_redirect_uris  text[] NOT NULL DEFAULT '{}',
  created_at             timestamptz NOT NULL DEFAULT now()
);

-- OAuth 2.1 authorization codes with PKCE support. Single-use, 10-min TTL.
-- Exchanged by the client at /token for access tokens (ZYND JWTs or opaque tokens).
CREATE TABLE IF NOT EXISTS oauth_codes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code            text NOT NULL UNIQUE,
  user_id         uuid NOT NULL REFERENCES users(id),
  client_id       text NOT NULL,
  redirect_uri    text NOT NULL,
  code_challenge  text,                                    -- null = no PKCE (legacy ChatGPT flow)
  code_challenge_method text DEFAULT 'S256',
  scope           text NOT NULL DEFAULT 'user',
  expires_at      timestamptz NOT NULL,
  used_at         timestamptz,                             -- null = not yet used
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- OAuth opaque access tokens — issued when the /token endpoint returns a non-JWT
-- token (e.g. for providers that require opaque strings). ZYND JWTs are
-- self-contained and don't use this table; it's a fallback for opaque tokens.
CREATE TABLE IF NOT EXISTS oauth_access_tokens (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token           text NOT NULL UNIQUE,
  user_id         uuid NOT NULL REFERENCES users(id),
  client_id       text NOT NULL,
  scopes          text[] NOT NULL DEFAULT '{user}',
  expires_at      timestamptz NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);
