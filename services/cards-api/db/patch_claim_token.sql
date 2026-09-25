-- One-time claim tokens for anonymously published cards.
--
-- An anonymous publish stores sha256(token) here and returns the token once;
-- the publisher sends it as X-Claim-Token on the PATCH that claims the card.
-- Cleared on claim. Unowned cards without a hash (published before this patch)
-- can only be claimed when LEGACY_UNOWNED_CLAIM=true.
--
-- Apply BEFORE deploying the code that reads/writes this column.

alter table agent_profile_cards
  add column if not exists claim_token_hash text;
