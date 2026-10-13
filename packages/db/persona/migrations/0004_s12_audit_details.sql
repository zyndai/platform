-- owner: persona
-- Keep policy changes/denied requests auditable without logging request bodies.
-- Rollback: flags off; retain the additive audit metadata column.
ALTER TABLE "persona_intro_audit" ADD COLUMN "details" jsonb DEFAULT '{}'::jsonb NOT NULL;
