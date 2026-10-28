-- owner: cards
-- "Working on" freshness. A card's Working on list is written by cards-api (publish, the editor's
-- full-card PATCH, beacons), by cards.s10_save_section (editor section saves) and by
-- cards.companion_save_fields (the browser extension), and none of them records when the list last
-- changed, so a six-month-old "Working on" reads as current to visitors and AI agents.
-- working_on_updated_at is that time. A trigger stamps it whenever card->'working_on' changes, so
-- every writer above (and any future one, or a hand-run UPDATE) is covered without touching them.
-- The owner's "Still working on this" confirm sets the column explicitly; the trigger keeps an
-- explicit value when the list itself did not change, and never lets it sit in the future.
-- The trigger also mirrors the value into card->'working_on_updated_at', so every existing reader
-- of the card JSON gets it without selecting a new column. The column is the authority: the
-- mirror is rewritten from it on every write, so a stale copy of the card JSON cannot move it.
-- Expand-only: one nullable column, one function, one trigger, no backfill. Existing rows stay
-- NULL = "unknown", which cards-api and cards-web treat as NOT stale, and their card JSON is
-- unchanged until the next write that touches `card`. cards-api tolerates this migration being
-- absent (the confirm endpoint answers 503, nothing is ever shown as stale), so it can be applied
-- before or after the deploy. Do not apply to prod without a human (AGENTS.md §6).
-- Rollback: first set FEATURE_STALE_SIGNALS=false on cards-api (a request that read the card
-- before the UPDATE below can write the mirror key back; with the flag off it is never shown),
-- then run:
--   DROP TRIGGER IF EXISTS agent_profile_cards_working_on_stamp ON cards.agent_profile_cards;
--   DROP FUNCTION IF EXISTS cards.stamp_working_on_updated_at();
--   UPDATE cards.agent_profile_cards SET card = card - 'working_on_updated_at' WHERE card ? 'working_on_updated_at';
--   ALTER TABLE cards.agent_profile_cards DROP COLUMN IF EXISTS working_on_updated_at;
--   DELETE FROM drizzle.__cards_migrations WHERE created_at = 1793183055198;  -- this file's journal "when", so it can be re-applied later
-- ADD COLUMN takes an ACCESS EXCLUSIVE lock on the busiest cards table. Fail fast instead of
-- queueing every card read and write behind a long-running query; retry in a quieter moment.
SET LOCAL lock_timeout = '5s';
--> statement-breakpoint
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "working_on_updated_at" timestamp with time zone;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.stamp_working_on_updated_at()
RETURNS trigger LANGUAGE plpgsql SET search_path = cards, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.working_on_updated_at IS NULL AND jsonb_typeof(NEW.card->'working_on') = 'array'
       AND jsonb_array_length(NEW.card->'working_on') > 0 THEN
      NEW.working_on_updated_at := now();
    END IF;
  ELSIF NEW.card->'working_on' IS DISTINCT FROM OLD.card->'working_on' THEN
    NEW.working_on_updated_at := now();
  END IF;
  -- A future stamp would hide staleness forever.
  IF NEW.working_on_updated_at > now() THEN
    NEW.working_on_updated_at := now();
  END IF;
  IF jsonb_typeof(NEW.card) = 'object' THEN
    IF NEW.working_on_updated_at IS NULL THEN
      IF NEW.card ? 'working_on_updated_at' THEN
        NEW.card := NEW.card - 'working_on_updated_at';
      END IF;
    ELSIF NEW.card->'working_on_updated_at' IS DISTINCT FROM to_jsonb(NEW.working_on_updated_at) THEN
      NEW.card := jsonb_set(NEW.card, '{working_on_updated_at}', to_jsonb(NEW.working_on_updated_at));
    END IF;
  END IF;
  RETURN NEW;
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION cards.stamp_working_on_updated_at() FROM PUBLIC, anon, authenticated;
--> statement-breakpoint
-- UPDATE OF: embedding-only and status-only updates never touch `card`, so they skip the trigger.
CREATE TRIGGER agent_profile_cards_working_on_stamp
BEFORE INSERT OR UPDATE OF card, working_on_updated_at ON cards.agent_profile_cards
FOR EACH ROW EXECUTE FUNCTION cards.stamp_working_on_updated_at();
