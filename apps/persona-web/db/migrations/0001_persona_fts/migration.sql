-- Migration: persona full-text search
--
-- Adds two columns to persona_agents:
--   brief_content  TEXT       — cached body of the user's Google Doc brief
--   search_vector  TSVECTOR   — weighted FTS vector over all searchable fields
--
-- A BEFORE INSERT OR UPDATE trigger keeps search_vector in sync automatically.
-- A GIN index makes tsvector queries fast.
-- A helper RPC (search_personas_fts) lets supabase-py call ranked FTS with
-- plainto_tsquery without needing to build raw SQL in Python.

-- 1. New columns (additive only — no existing data is modified or dropped)
ALTER TABLE persona_agents
  ADD COLUMN IF NOT EXISTS brief_content  TEXT,
  ADD COLUMN IF NOT EXISTS search_vector  TSVECTOR;

-- 2. Trigger function
--    Weights: A = name, B = description + title, C = everything else
--    The trigger only writes to NEW.search_vector — all other columns
--    in NEW are returned unchanged, so no existing data can be lost.
CREATE OR REPLACE FUNCTION persona_agents_search_vector_update()
RETURNS TRIGGER AS $$
DECLARE
  caps_text      TEXT;
  interests_text TEXT;
BEGIN
  -- capabilities is a JSONB array of strings e.g. ["content writing", "fundraising"]
  SELECT COALESCE(string_agg(val, ' '), '')
  INTO caps_text
  FROM jsonb_array_elements_text(
    CASE WHEN jsonb_typeof(NEW.capabilities) = 'array'
         THEN NEW.capabilities
         ELSE '[]'::jsonb
    END
  ) AS val;

  -- profile->interests can be a JSON array or a comma-separated string
  IF jsonb_typeof(NEW.profile->'interests') = 'array' THEN
    SELECT COALESCE(string_agg(val, ' '), '')
    INTO interests_text
    FROM jsonb_array_elements_text(NEW.profile->'interests') AS val;
  ELSE
    interests_text := COALESCE(NEW.profile->>'interests', '');
  END IF;

  NEW.search_vector :=
    setweight(to_tsvector('english', COALESCE(NEW.name,                       '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(NEW.description,                '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(NEW.profile->>'title',          '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(NEW.profile->>'organization',   '')), 'C') ||
    setweight(to_tsvector('english', caps_text),                                    'C') ||
    setweight(to_tsvector('english', interests_text),                               'C') ||
    setweight(to_tsvector('english', COALESCE(NEW.brief_content,              '')), 'C');

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Attach trigger (DROP+CREATE is the only idempotent way in older Postgres;
--    no data is affected — triggers operate on future writes only)
DROP TRIGGER IF EXISTS persona_agents_search_vector_trigger ON persona_agents;
CREATE TRIGGER persona_agents_search_vector_trigger
  BEFORE INSERT OR UPDATE ON persona_agents
  FOR EACH ROW EXECUTE FUNCTION persona_agents_search_vector_update();

-- 4. Backfill existing rows to populate search_vector.
--    We touch `active = active` (boolean no-op) to fire the BEFORE UPDATE
--    trigger without touching name, description, updated_at, or any other
--    column whose side-effects we'd need to audit. The trigger only modifies
--    NEW.search_vector and returns NEW unchanged otherwise.
UPDATE persona_agents SET active = active;

-- 5. GIN index for fast tsvector lookups.
--    persona_agents is a small table so the brief ShareLock here is negligible.
--    Safe to re-run: IF NOT EXISTS is a no-op when the index already exists.
CREATE INDEX IF NOT EXISTS persona_agents_search_vector_idx
  ON persona_agents USING GIN (search_vector);

-- 6. RPC helper: ranked FTS query callable from supabase-py via .rpc()
--    plainto_tsquery handles natural-language input (no special syntax needed).
CREATE OR REPLACE FUNCTION search_personas_fts(query_text TEXT, result_limit INT DEFAULT 24)
RETURNS TABLE (
  agent_id    TEXT,
  name        TEXT,
  description TEXT
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    pa.agent_id,
    pa.name,
    pa.description
  FROM persona_agents pa
  WHERE pa.active = TRUE
    AND pa.search_vector @@ plainto_tsquery('english', query_text)
  ORDER BY ts_rank(pa.search_vector, plainto_tsquery('english', query_text)) DESC
  LIMIT result_limit;
END;
$$ LANGUAGE plpgsql STABLE;
