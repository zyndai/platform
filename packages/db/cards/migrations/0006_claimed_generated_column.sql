-- owner: cards
-- S03: stored `claimed` flag so agent-facing queries can filter cheaply and
-- can never disagree with owner_email. GENERATED STORED (the equivalent
-- boolean was previously computed in SQL/Python). The email is never exposed
-- — only this boolean.
-- Rollback: DROP INDEX IF EXISTS cards.idx_cards_claimed;
--           ALTER TABLE cards.agent_profile_cards DROP COLUMN claimed;
ALTER TABLE "cards"."agent_profile_cards" ADD COLUMN "claimed" boolean GENERATED ALWAYS AS ("owner_email" IS NOT NULL) STORED;--> statement-breakpoint
CREATE INDEX "idx_cards_claimed" ON "cards"."agent_profile_cards" USING btree ("claimed");