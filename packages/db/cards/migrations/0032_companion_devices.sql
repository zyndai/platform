-- owner: cards
-- Zynd Companion browser extension (docs/plans/ZYND_COMPANION_PLAN.md). companion_devices holds one
-- row per paired browser: the SHA-256 of its token (never the token), the owner's email and when it
-- was last used or revoked. companion_save_fields is s10_save_section's row-locked compare-and-swap,
-- but allowed to touch only working_on and exploring, so a device token's reach is those two fields.
-- Expand-only: one new table and one new function, nothing existing changes. Service-role only.
-- Until it exists the /cards/companion routes answer 503 and nothing else is affected, so this can be
-- applied before or after the deploy. Needs a human (AGENTS.md §6): it adds a way to sign in.
-- Rollback (after reverting cards-api, which stops using them):
--   DROP FUNCTION cards.companion_save_fields(text,text,jsonb,jsonb);
--   DROP TABLE cards.companion_devices;
CREATE TABLE "cards"."companion_devices" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_email" text NOT NULL,
	"token_hash" text NOT NULL,
	"label" text DEFAULT '' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_used_at" timestamp with time zone DEFAULT now() NOT NULL,
	"revoked_at" timestamp with time zone,
	CONSTRAINT "companion_devices_label_check" CHECK (char_length(label) <= 80)
);
--> statement-breakpoint
ALTER TABLE "cards"."companion_devices" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE UNIQUE INDEX "companion_devices_token_hash_key" ON "cards"."companion_devices" USING btree ("token_hash");--> statement-breakpoint
CREATE INDEX "companion_devices_owner_idx" ON "cards"."companion_devices" USING btree ("owner_email") WHERE revoked_at IS NULL;--> statement-breakpoint
CREATE POLICY "service role full access on companion_devices" ON "cards"."companion_devices" AS PERMISSIVE FOR ALL TO "service_role" USING (true) WITH CHECK (true);

--> statement-breakpoint
CREATE OR REPLACE FUNCTION cards.companion_save_fields(p_email text, p_handle text, p_patch jsonb, p_expected jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path = cards, pg_temp AS $$
DECLARE r cards.agent_profile_cards%ROWTYPE; key text; next_card jsonb;
BEGIN
  SELECT * INTO r FROM cards.agent_profile_cards WHERE handle = p_handle FOR UPDATE;
  IF NOT FOUND OR lower(r.owner_email) IS DISTINCT FROM lower(p_email) OR r.status = 'merged' THEN
    RAISE EXCEPTION 'not the card owner' USING ERRCODE = '42501';
  END IF;
  IF jsonb_typeof(p_patch) <> 'object' OR jsonb_typeof(p_expected) <> 'object' THEN
    RAISE EXCEPTION 'invalid fields' USING ERRCODE = '22023';
  END IF;
  FOR key IN SELECT jsonb_object_keys(p_patch) LOOP
    IF key NOT IN ('working_on', 'exploring') OR NOT (p_expected ? key)
       OR jsonb_typeof(p_patch->key) <> 'array' OR jsonb_array_length(p_patch->key) > 20 THEN
      RAISE EXCEPTION 'invalid fields' USING ERRCODE = '22023';
    END IF;
    -- A key the card has never held reads as an empty list, so the first clip does not conflict.
    IF coalesce(r.card->key, '[]'::jsonb) IS DISTINCT FROM p_expected->key THEN
      RAISE EXCEPTION 'fields changed; reload before saving' USING ERRCODE = '40001';
    END IF;
  END LOOP;
  next_card := r.card || p_patch || jsonb_build_object('updated_at', now());
  UPDATE cards.agent_profile_cards SET card = next_card, updated_at = now(),
    embedding = CASE WHEN p_patch ? 'working_on' THEN NULL ELSE embedding END WHERE id = r.id;
  RETURN next_card || jsonb_build_object('handle', r.handle, 'status', r.status);
END $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION cards.companion_save_fields(text,text,jsonb,jsonb) FROM PUBLIC, anon, authenticated;
--> statement-breakpoint
GRANT EXECUTE ON FUNCTION cards.companion_save_fields(text,text,jsonb,jsonb) TO service_role;
