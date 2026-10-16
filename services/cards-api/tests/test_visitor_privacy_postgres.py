"""Consent SQL on a strictly guarded disposable local Postgres; no shared DB."""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

DSN = os.getenv('VISITOR_TEST_DATABASE_URL', '')
pytestmark = pytest.mark.skipif(not DSN, reason='Disposable visitor database not configured')
ROOT = Path(__file__).resolve().parents[3]
OWNER = '11111111-1111-4111-8111-111111111111'
VISITOR = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
VISIT = '44444444-4444-4444-8444-444444444444'


def sql(statement):
    url = urlparse(DSN)
    assert url.hostname in {'127.0.0.1', 'localhost'} and url.port == 5549 and url.path == '/s10_visits_rehearsal', 'Only the disposable visitor DB is permitted'
    return subprocess.run(['psql', DSN, '-X', '-qAt', '-v', 'ON_ERROR_STOP=1'], input=statement, text=True, capture_output=True)


@pytest.fixture(scope='module', autouse=True)
def schema():
    if not DSN:
        return
    exists = sql("SELECT to_regclass('cards.profile_visits') IS NOT NULL;")
    assert exists.returncode == 0, exists.stderr
    if exists.stdout.strip() == 't':
        return
    setup = (ROOT / 'packages/db/test/supabase-stubs.sql').read_text()
    setup += '''
      CREATE SCHEMA cards;
      GRANT USAGE ON SCHEMA cards TO service_role;
      CREATE TABLE cards.agent_profile_cards(id text PRIMARY KEY,handle text,status text,owner_email text,owner_user_id uuid);
    '''
    for name in ['0015_s10_visitor_privacy.sql', '0016_s10_visitor_consent_operations.sql', '0017_s10_visit_owner_binding.sql']:
        setup += (ROOT / 'packages/db/cards/migrations' / name).read_text()
    result = sql('BEGIN;' + setup + 'COMMIT;')
    assert result.returncode == 0, result.stderr


SEED = f'''
BEGIN;
SET LOCAL request.jwt.claim.role='service_role';
INSERT INTO auth.users(id) VALUES('{OWNER}'),('{VISITOR}'),('{OTHER}');
INSERT INTO cards.agent_profile_cards VALUES('c1','alice','published','alice@example.com','{OWNER}');
'''
RECORD = f"SELECT cards.s10_record_named_visit('{VISIT}','{VISITOR}','bob@example.com','alice','Bob');"
OPTIN = f"SELECT cards.s10_set_visitor_privacy('{VISITOR}',false,'Bob');"
LIST = "cards.s10_named_visitors('alice','alice@example.com')"


def check(statement, expected='t'):
    result = sql(SEED + statement + 'ROLLBACK;')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == expected, result.stdout


def test_default_anonymous_is_not_recorded():
    check(RECORD + 'SELECT count(*)=0 FROM cards.profile_visits;')


def test_optin_records_once_and_exposes_only_name_time_count():
    check(OPTIN + RECORD + RECORD + f'''SELECT (SELECT count(*)=1 FROM cards.profile_visits)
      AND {LIST}->0->>'name'='Bob' AND {LIST}->0->>'visits'='1'
      AND NOT ({LIST}->0 ? 'visitor_id') AND NOT ({LIST}->0 ? 'owner_email');''')


def test_revocation_hides_names_and_new_optin_does_not_restore_old_visits():
    check(OPTIN + RECORD + f'''
      SELECT cards.s10_set_visitor_privacy('{VISITOR}',true,'Bob');
      DO $$ BEGIN IF {LIST} <> '[]'::jsonb THEN RAISE EXCEPTION 'Revocation leaked names'; END IF; END $$;
      SELECT cards.s10_set_visitor_privacy('{VISITOR}',false,'Bob');
      SELECT {LIST}='[]'::jsonb;
    ''')


def test_new_visit_after_reoptin_uses_new_consent_epoch():
    check(OPTIN + RECORD + f'''
      SELECT cards.s10_set_visitor_privacy('{VISITOR}',true,'Bob');
      SELECT cards.s10_set_visitor_privacy('{VISITOR}',false,'Bob');
      SELECT cards.s10_record_named_visit('{OTHER}','{VISITOR}','bob@example.com','alice','Bob');
      SELECT {LIST}->0->>'visits'='1';
    ''')


def test_other_owner_cannot_read_list():
    check(OPTIN + RECORD + '''DO $$ BEGIN
      PERFORM cards.s10_named_visitors('alice','mallory@example.com');
      RAISE EXCEPTION 'Expected owner refusal';
      EXCEPTION WHEN insufficient_privilege THEN NULL; END $$; SELECT true;''')


def test_owner_transfer_does_not_expose_previous_owners_visitor_history():
    check(OPTIN + RECORD + f'''UPDATE cards.agent_profile_cards SET owner_email='cara@example.com',owner_user_id='{OTHER}';
      SELECT cards.s10_named_visitors('alice','cara@example.com')='[]'::jsonb;''')


def test_private_cards_and_self_visits_are_not_named():
    check(OPTIN + f'''UPDATE cards.agent_profile_cards SET status='private';''' + RECORD + f'''
      UPDATE cards.agent_profile_cards SET status='published';
      SELECT cards.s10_record_named_visit('{VISIT}','{VISITOR}','alice@example.com','alice','Bob');
      SELECT count(*)=0 FROM cards.profile_visits;
    ''')


def test_authenticated_clients_cannot_read_tables_or_call_privileged_functions():
    check('''SET LOCAL ROLE authenticated; SET LOCAL request.jwt.claim.role='authenticated';
      DO $$ BEGIN PERFORM * FROM cards.profile_visits; RAISE EXCEPTION 'Expected table refusal';
        EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
      DO $$ BEGIN PERFORM cards.s10_named_visitors('alice','alice@example.com'); RAISE EXCEPTION 'Expected RPC refusal';
        EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
      RESET ROLE; SELECT true;
    ''')


def test_account_deletion_cascades_visitor_data():
    check(OPTIN + RECORD + f'''DELETE FROM auth.users WHERE id='{VISITOR}';
      SELECT (SELECT count(*)=0 FROM cards.visitor_preferences) AND (SELECT count(*)=0 FROM cards.profile_visits);''')
