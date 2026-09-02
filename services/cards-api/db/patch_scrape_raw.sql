-- Migration: add scrape_raw and user_intent columns
-- Run: psql "$DIRECT_URL" -f patch_scrape_raw.sql
alter table agent_profile_cards add column if not exists scrape_raw jsonb;
alter table agent_profile_cards add column if not exists user_intent jsonb;
