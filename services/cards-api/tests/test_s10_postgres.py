"""Real S10 transaction rehearsal on a disposable local Postgres only.

S10_TEST_DATABASE_URL=postgresql://shiv@127.0.0.1:5548/s10_rehearsal pytest ...
The minimal pre-S10 table avoids requiring pgvector for these transactions;
full-history schema drift remains the packages/db CI responsibility.
"""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

DSN = os.getenv("S10_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="S10 temporary Postgres not configured")
MIGRATIONS = Path(__file__).resolve().parents[3] / "packages/db/cards/migrations"


def sql(statement):
    url = urlparse(DSN)
    assert url.hostname in {"127.0.0.1", "localhost"} and url.port == 5548 and url.path == "/s10_rehearsal", "Only the disposable S10 database is allowed"
    return subprocess.run(["psql", DSN, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"], input=statement, text=True, capture_output=True)


@pytest.fixture(scope="module", autouse=True)
def schema():
    if not DSN:
        return
    if sql("SELECT to_regclass('cards.agent_profile_cards') IS NOT NULL;").stdout.strip() == "t":
        result = sql((MIGRATIONS / "0011_s10_owner_operations.sql").read_text())
        assert result.returncode == 0, result.stderr
        return
    base = """
    DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    CREATE SCHEMA cards;
    GRANT USAGE ON SCHEMA cards TO service_role;
    ALTER DEFAULT PRIVILEGES IN SCHEMA cards GRANT ALL ON TABLES TO service_role;
    CREATE TABLE cards.agent_profile_cards(
      id text PRIMARY KEY, handle text UNIQUE, alias text UNIQUE,
      status text NOT NULL DEFAULT 'published', owner_email text, card jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), embedding text);
    """
    result = sql(base + (MIGRATIONS / "0010_s10_owner_home.sql").read_text() + (MIGRATIONS / "0011_s10_owner_operations.sql").read_text())
    assert result.returncode == 0, result.stderr


SEED = """
BEGIN;
INSERT INTO cards.agent_profile_cards(id,handle,alias,owner_email,card) VALUES
 ('c1','alice','a','alice@example.com','{"id":"c1","summary":"Before","identity":{"name":"Alice"},"zynd_memory":[{"object":"Python"}]}'),
 ('c2','alice-old','old','alice@example.com','{"id":"c2","summary":"Old card"}'),
 ('c3','bob',NULL,'bob@example.com','{"id":"c3","summary":"Bob"}');
"""


def check(statement, expected):
    result = sql(SEED + statement + "ROLLBACK;")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == expected


def test_merge_archives_preserves_and_audits():
    check("""
    SELECT cards.s10_merge('alice@example.com','c1',ARRAY['c2']);
    SELECT (SELECT status = 'merged' AND merged_into = 'c1' AND card->>'summary' = 'Old card' FROM cards.agent_profile_cards WHERE id='c2')
      AND (SELECT count(*)=3 FROM cards.agent_profile_cards)
      AND (SELECT count(*)=1 FROM cards.card_merges)
      AND (SELECT card->'previous_handles' @> '["alice-old"]'::jsonb FROM cards.agent_profile_cards WHERE id='c1');
    """, "t")


def test_merge_idempotent():
    check("""
    SELECT cards.s10_merge('alice@example.com','c1',ARRAY['c2']);
    SELECT cards.s10_merge('alice@example.com','c1',ARRAY['c2']);
    SELECT count(*) FROM cards.card_merges;
    """, "1")


def test_merge_invalid_owner_rolls_back_every_source():
    check("""
    DO $$ BEGIN
      PERFORM cards.s10_merge('alice@example.com','c1',ARRAY['c2','c3']);
      RAISE EXCEPTION 'Expected ownership rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    SELECT (SELECT count(*)=0 FROM cards.card_merges)
      AND (SELECT count(*)=0 FROM cards.agent_profile_cards WHERE status='merged');
    """, "t")


def test_merge_flattens_existing_redirects():
    check("""
    INSERT INTO cards.agent_profile_cards(id,handle,owner_email,card) VALUES('c4','alice-new','alice@example.com','{"id":"c4"}');
    SELECT cards.s10_merge('alice@example.com','c1',ARRAY['c2']);
    SELECT cards.s10_merge('alice@example.com','c4',ARRAY['c1']);
    SELECT count(*) FROM cards.agent_profile_cards WHERE merged_into='c4';
    """, "2")


def test_partial_save_preserves_concurrent_memory():
    check("""
    SELECT cards.s10_save_section('alice@example.com','alice','{"summary":"After"}','{"summary":"Before"}');
    SELECT card->>'summary'='After' AND card->'zynd_memory'='[{"object":"Python"}]'::jsonb FROM cards.agent_profile_cards WHERE id='c1';
    """, "t")


def test_system_refresh_preserves_owner_section_and_identity():
    check("""
    SELECT cards.s10_save_section('alice@example.com','alice','{"summary":"Owner edit"}','{"summary":"Before"}');
    SELECT cards.s10_patch_system_fields('alice','{"zynd_memory":[],"avatar_url":"https://photo.test/alice"}');
    SELECT card->>'summary'='Owner edit' AND card->'identity'->>'name'='Alice' AND card->'zynd_memory'='[]'::jsonb FROM cards.agent_profile_cards WHERE id='c1';
    """, "t")


def test_stale_section_save_rejected_and_first_edit_survives():
    check("""
    SELECT cards.s10_save_section('alice@example.com','alice','{"summary":"First"}','{"summary":"Before"}');
    DO $$ BEGIN
      PERFORM cards.s10_save_section('alice@example.com','alice','{"summary":"Stale"}','{"summary":"Before"}');
      RAISE EXCEPTION 'Expected conflict';
    EXCEPTION WHEN serialization_failure THEN NULL; END $$;
    SELECT card->>'summary' FROM cards.agent_profile_cards WHERE id='c1';
    """, "First")


def test_sparse_identity_raw_expectation_can_be_saved():
    check("""
    SELECT cards.s10_save_section('alice@example.com','alice','{"identity":{"name":"Alice Updated"}}',
      '{"identity":{"name":"Alice"}}');
    SELECT card->'identity'->>'name' FROM cards.agent_profile_cards WHERE id='c1';
    """, "Alice Updated")


def test_visibility_keeps_json_and_row_in_sync():
    check("""
    SELECT cards.s10_visibility('alice@example.com','alice',false);
    SELECT status='private' AND card->>'status'='private' FROM cards.agent_profile_cards WHERE id='c1';
    """, "t")


def test_delivery_and_expiry_nudge_unique_constraints():
    check("""
    INSERT INTO cards.notification_deliveries(owner_email,kind,period) VALUES('alice@example.com','weekly','2026-W42');
    INSERT INTO cards.notification_deliveries(owner_email,kind,period) VALUES('alice@example.com','weekly','2026-W42') ON CONFLICT DO NOTHING;
    INSERT INTO cards.card_nudges(owner_email,handle,dedupe_key,kind,title,href) VALUES('alice@example.com','alice','expiring:same','expiring','Expires','/home');
    INSERT INTO cards.card_nudges(owner_email,handle,dedupe_key,kind,title,href) VALUES('alice@example.com','alice','expiring:same','expiring','Expires','/home') ON CONFLICT DO NOTHING;
    SELECT (SELECT count(*)=1 FROM cards.notification_deliveries) AND (SELECT count(*)=1 FROM cards.card_nudges);
    """, "t")


def test_rpc_never_executable_by_public_users():
    check("SELECT NOT has_function_privilege('anon','cards.s10_merge(text,text,text[])','EXECUTE') AND NOT has_function_privilege('authenticated','cards.s10_save_section(text,text,jsonb,jsonb)','EXECUTE');", "t")
