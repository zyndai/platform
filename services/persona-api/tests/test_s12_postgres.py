"""Rehearse S12 on a disposable local database; never connect to shared Supabase."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest

DSN = os.getenv("S12_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    not DSN, reason="Disposable S12 Postgres not configured"
)
OWNER = "00000000-0000-0000-0000-000000000001"
REQUESTER = "00000000-0000-0000-0000-000000000002"
OTHER = "00000000-0000-0000-0000-000000000003"
KEY = "00000000-0000-0000-0000-000000000004"


def sql(statement):
    target = urlparse(DSN)
    assert (
        target.hostname in {"localhost", "127.0.0.1"}
        and target.port == 5549
        and target.path == "/s12_rehearsal"
    ), "Only the disposable S12 database is allowed"
    return subprocess.run(
        ["psql", DSN, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=statement,
        text=True,
        capture_output=True,
    )


@pytest.fixture(scope="module", autouse=True)
def schema():
    if not DSN:
        return
    exists = sql("SELECT to_regclass('public.persona_intro_requests') IS NOT NULL;")
    assert exists.returncode == 0, exists.stderr
    scripts = []
    if exists.stdout.strip() != "t":
        scripts = [ROOT / "packages/db/test/supabase-stubs.sql"]
        scripts += sorted((ROOT / "packages/db/persona/migrations").glob("*.sql"))
    else:
        scripts = []
        has_details = (
            sql(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='persona_intro_audit' AND column_name='details');"
            ).stdout.strip()
            == "t"
        )
        if not has_details:
            scripts.append(
                ROOT / "packages/db/persona/migrations/0004_s12_audit_details.sql"
            )
        scripts.append(
            ROOT / "packages/db/persona/migrations/0003_s12_intro_operations.sql"
        )
    if exists.stdout.strip() == "t":
        scripts.append(
            ROOT / "packages/db/persona/migrations/0005_s12_deletion_compatibility.sql"
        )
    if exists.stdout.strip() == "t":
        scripts.append(
            ROOT / "packages/db/persona/migrations/0006_s12_meeting_grants.sql"
        )
    setup = "\n".join(path.read_text() for path in scripts)
    setup += """
    CREATE SCHEMA IF NOT EXISTS cards;
    GRANT USAGE ON SCHEMA cards TO service_role;
    CREATE TABLE IF NOT EXISTS cards.agent_profile_cards(id text PRIMARY KEY,handle text,status text,owner_user_id uuid);
    CREATE TABLE IF NOT EXISTS cards.card_events(id bigserial PRIMARY KEY,event text,handle text,actor_class text,meta jsonb,ts timestamptz);
    """
    if (
        sql("SELECT to_regclass('cards.intro_requests') IS NOT NULL;").stdout.strip()
        != "t"
    ):
        setup += (
            ROOT / "packages/db/cards/migrations/0012_s12_intro_projection.sql"
        ).read_text()
    setup += (
        ROOT / "packages/db/cards/migrations/0013_s12_intro_events.sql"
    ).read_text()
    setup += (
        ROOT / "packages/db/cards/migrations/0014_s12_deletion_compatibility.sql"
    ).read_text()
    result = sql("BEGIN;" + setup + "COMMIT;")
    assert result.returncode == 0, result.stderr


SEED = f"""
BEGIN;
SET LOCAL request.jwt.claim.role='service_role';
INSERT INTO auth.users(id) VALUES ('{OWNER}'),('{REQUESTER}'),('{OTHER}');
INSERT INTO public.persona_agents(user_id,agent_id,derivation_index,public_key,name) VALUES
 ('{OWNER}','owner-agent',1,'test','Alice'),('{REQUESTER}','requester-agent',2,'test','Bob'),('{OTHER}','other-agent',3,'test','Cara');
INSERT INTO cards.agent_profile_cards(id,handle,status,owner_user_id) VALUES('c1','alice','published','{OWNER}');
"""


def create(
    key=KEY,
    requester=REQUESTER,
    owner=OWNER,
    card="c1",
    why="Can we discuss Python APIs?",
    requester_cap=10,
    card_cap=20,
):
    return f"public.s12_create_intro('{card}','alice','{requester}','{owner}','{why}','[\"meeting\",\"message\"]','{key}',{requester_cap},{card_cap})"


def check(statement, expected):
    result = sql(SEED + statement + "ROLLBACK;")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == expected, result.stdout


def test_retry_creates_one_thread_request_and_audit():
    check(
        f"SELECT {create()}; SELECT {create()}; SELECT (SELECT count(*)=1 FROM persona_intro_requests) AND (SELECT count(*)=1 FROM dm_threads) AND (SELECT count(*)=1 FROM persona_intro_audit);",
        "t",
    )


def test_same_key_different_content_is_refused():
    check(
        f"SELECT {create()}; SELECT {create(why='Different request using the same key')}->>'error';",
        "idempotency_conflict",
    )


def test_owner_approval_and_meeting_proposal_are_atomic_and_idempotent():
    check(
        f"""
    SELECT {create()};
    SELECT s12_respond_intro(id,'{OWNER}','accept',true,now()+interval '1 day',now()+interval '1 day 20 minutes') FROM persona_intro_requests;
    SELECT s12_respond_intro(id,'{OWNER}','accept',true,now()+interval '1 day',now()+interval '1 day 20 minutes') FROM persona_intro_requests;
    SELECT (SELECT count(*)=1 FROM agent_tasks WHERE status='proposed')
      AND (SELECT status='accepted' AND (permissions->>'can_request_meetings')::boolean
        AND NOT (permissions->>'can_post_on_my_behalf')::boolean FROM dm_threads)
      AND (SELECT count(*)=3 FROM persona_intro_audit);
    """,
        "t",
    )


def test_requester_cannot_accept_and_failed_decision_leaves_pending():
    check(
        f"""
    SELECT {create()};
    DO $$ BEGIN
      PERFORM s12_respond_intro(id,'{REQUESTER}','accept',true) FROM persona_intro_requests;
      RAISE EXCEPTION 'Expected owner rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    SELECT status='pending' AND (SELECT count(*)=0 FROM agent_tasks) FROM persona_intro_requests;
    """,
        "t",
    )


def test_decline_and_conflicting_accept_preserve_decision():
    check(
        f"""
    SELECT {create()};
    SELECT s12_respond_intro(id,'{OWNER}','decline',false) FROM persona_intro_requests;
    DO $$ BEGIN
      PERFORM s12_respond_intro(id,'{OWNER}','accept',true) FROM persona_intro_requests;
      RAISE EXCEPTION 'Expected conflict';
    EXCEPTION WHEN serialization_failure THEN NULL; END $$;
    SELECT status='declined' AND (SELECT count(*)=0 FROM agent_tasks) FROM persona_intro_requests;
    """,
        "t",
    )


def test_limits_and_allow_deny_rules_leave_audit_without_connection():
    check(
        f"""
    INSERT INTO persona_intro_rules VALUES('{OWNER}','{OTHER}','allow');
    SELECT {create()}->>'error';
    """,
        "denied",
    )
    check(
        f"""
    INSERT INTO persona_intro_rules VALUES('{OWNER}','{REQUESTER}','deny');
    SELECT {create()};
    SELECT (SELECT count(*)=0 FROM dm_threads) AND (SELECT action='denied' FROM persona_intro_audit);
    """,
        "t",
    )
    check(
        f"SELECT {create(card_cap=1)}; SELECT {create(key=OTHER, requester=OTHER, card_cap=1)}->>'error';",
        "rate_limited",
    )
    check(
        f"SELECT {create(requester_cap=1)}; SELECT {create(key=OTHER, owner=OTHER, card='c2', requester_cap=1)}->>'error';",
        "rate_limited",
    )


def test_direct_authenticated_writes_cannot_grant_permissions_or_accept():
    check(
        f"""
    SELECT {create()};
    SET LOCAL request.jwt.claim.role='authenticated';
    SET LOCAL request.jwt.claim.sub='{REQUESTER}';
    SET LOCAL ROLE authenticated;
    DO $$ BEGIN
      UPDATE dm_threads SET permissions='{{"can_post_on_my_behalf":true}}';
      RAISE EXCEPTION 'Expected permission rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    DO $$ BEGIN
      UPDATE dm_threads SET status='accepted';
      RAISE EXCEPTION 'Expected acceptance rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    SELECT status='pending' AND NOT (permissions->>'can_post_on_my_behalf')::boolean FROM dm_threads;
    """,
        "t",
    )


def test_rpc_execute_is_not_granted_to_humans():
    check(
        "SELECT NOT has_function_privilege('authenticated','public.s12_respond_intro(uuid,uuid,text,boolean,timestamptz,timestamptz)','execute');",
        "t",
    )


def test_projection_and_activity_events_are_written_once():
    check(
        f"""
    SELECT {create()};
    SELECT cards.s12_sync_intro(to_jsonb(r),true) FROM persona_intro_requests r;
    SELECT cards.s12_sync_intro(to_jsonb(r),true) FROM persona_intro_requests r;
    SELECT s12_respond_intro(id,'{OWNER}','accept',false) FROM persona_intro_requests;
    SELECT cards.s12_sync_intro(to_jsonb(r),true) FROM persona_intro_requests r;
    SELECT cards.s12_sync_intro(to_jsonb(r),true) FROM persona_intro_requests r;
    SELECT (SELECT count(*)=1 FROM cards.intro_requests) AND (SELECT count(*)=2 FROM cards.card_events);
    """,
        "t",
    )


def test_revoked_meeting_permission_is_enforced_at_proposal():
    check(
        f"""
    SELECT {create()};
    SELECT s12_respond_intro(id,'{OWNER}','accept',true) FROM persona_intro_requests;
    UPDATE dm_threads SET permissions=jsonb_set(permissions,'{{can_request_meetings}}','false');
    DO $$ BEGIN
      PERFORM s12_respond_intro(id,'{OWNER}','propose_time',false,now()+interval '1 day',now()+interval '1 day 20 minutes') FROM persona_intro_requests;
      RAISE EXCEPTION 'Expected revoked permission rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    SELECT count(*)=0 FROM agent_tasks;
    """,
        "t",
    )


def test_permission_changes_require_owner_and_cannot_exceed_snapshot():
    check(
        f"""
    SELECT {create()};
    SELECT s12_respond_intro(id,'{OWNER}','accept',true) FROM persona_intro_requests;
    DO $$ BEGIN
      PERFORM s12_save_thread_permissions(thread_id,'{REQUESTER}','{{"can_post_on_my_behalf":true}}') FROM persona_intro_requests;
      RAISE EXCEPTION 'Expected requester rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    DO $$ BEGIN
      PERFORM s12_save_thread_permissions(thread_id,'{OWNER}','{{"can_post_on_my_behalf":true}}') FROM persona_intro_requests;
      RAISE EXCEPTION 'Expected snapshot rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    SELECT s12_save_thread_permissions(thread_id,'{OWNER}','{{"can_request_meetings":false}}') FROM persona_intro_requests;
    SELECT (SELECT NOT (permissions->>'can_request_meetings')::boolean FROM dm_threads)
      AND (SELECT count(*)=1 FROM persona_intro_audit WHERE action='permissions_changed');
    """,
        "t",
    )


def test_pending_thread_cannot_be_used_to_bypass_intro_approval():
    check(
        f"""
    SELECT {create()};
    SET LOCAL request.jwt.claim.role='authenticated'; SET LOCAL request.jwt.claim.sub='{REQUESTER}';
    SET LOCAL ROLE authenticated;
    DO $$ BEGIN
      INSERT INTO dm_messages(thread_id,sender_id,content) SELECT id,'{REQUESTER}','Unapproved message' FROM dm_threads;
      RAISE EXCEPTION 'Expected pending-message rejection';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
    SELECT count(*)=1 FROM dm_messages;
    """,
        "t",
    )


def test_rule_changes_are_audited_atomically():
    check(
        f"""
    SELECT s12_set_intro_rule('{OWNER}','{REQUESTER}','deny');
    SELECT s12_set_intro_rule('{OWNER}','{REQUESTER}',NULL);
    SELECT (SELECT count(*)=0 FROM persona_intro_rules) AND
      (SELECT count(*)=2 FROM persona_intro_audit WHERE details->>'requester_uid'='{REQUESTER}');
    """,
        "t",
    )


def test_late_projection_keeps_acceptance_after_block_and_does_not_regress():
    check(
        f"""
    SELECT {create()};
    SELECT s12_respond_intro(id,'{OWNER}','accept',false) FROM persona_intro_requests;
    SELECT s12_respond_intro(id,'{OWNER}','block',false) FROM persona_intro_requests;
    SELECT cards.s12_sync_intro(to_jsonb(r)||jsonb_build_object('accepted_at',
      (SELECT created_at FROM persona_intro_audit WHERE action='accepted')),true) FROM persona_intro_requests r;
    SELECT cards.s12_sync_intro(to_jsonb(r)||jsonb_build_object('status','pending'),true) FROM persona_intro_requests r;
    SELECT (SELECT status='blocked' FROM cards.intro_requests) AND (SELECT count(*)=2 FROM cards.card_events);
    """,
        "t",
    )


def test_concurrent_retries_create_one_request():
    owner, requester, key = map(str, (uuid4(), uuid4(), uuid4()))
    index = int(owner.replace("-", ""), 16) % 1_000_000_000 + 10000
    seed = sql(
        f"INSERT INTO auth.users(id) VALUES('{owner}'),('{requester}'); INSERT INTO persona_agents(user_id,agent_id,derivation_index,public_key,name) VALUES('{owner}','{owner}',{index},'test','Owner'),('{requester}','{requester}',{index + 1},'test','Requester');"
    )
    assert seed.returncode == 0, seed.stderr
    statement = (
        "SET request.jwt.claim.role='service_role'; SELECT "
        + create(key=key, requester=requester, owner=owner, card="concurrent")
        + "->>'id';"
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(sql, [statement, statement]))
    assert all(result.returncode == 0 for result in results), [
        r.stderr for r in results
    ]
    assert results[0].stdout.strip() == results[1].stdout.strip()
    # Remove only this test's generated users/requests from the disposable DB.
    cleanup = sql(
        f"DELETE FROM persona_intro_audit WHERE owner_uid='{owner}'; WITH removed AS (DELETE FROM persona_intro_requests WHERE owner_uid='{owner}' RETURNING thread_id) DELETE FROM dm_threads WHERE id IN (SELECT thread_id FROM removed); DELETE FROM persona_agents WHERE user_id IN ('{owner}','{requester}'); DELETE FROM auth.users WHERE id IN ('{owner}','{requester}');"
    )
    assert cleanup.returncode == 0, cleanup.stderr


def test_existing_account_deletion_is_not_blocked_by_intros():
    check(
        f"""
        SELECT {create()};
        SELECT s12_set_intro_rule('{OWNER}','{REQUESTER}','deny');
        SELECT cards.s12_sync_intro(to_jsonb(r),false) FROM persona_intro_requests r;
        DELETE FROM dm_threads;
        DELETE FROM auth.users WHERE id='{REQUESTER}';
        SELECT NOT EXISTS(SELECT 1 FROM persona_intro_requests)
          AND NOT EXISTS(SELECT 1 FROM persona_intro_audit WHERE intro_id IS NOT NULL)
          AND NOT EXISTS(SELECT 1 FROM persona_intro_rules)
          AND NOT EXISTS(SELECT 1 FROM cards.intro_requests);
        """,
        "t",
    )


def test_existing_meeting_ticket_cannot_be_accepted_after_permission_revocation():
    check(
        f"""
        SELECT {create()};
        SELECT s12_respond_intro(id,'{OWNER}','accept',true,now()+interval '1 day',now()+interval '1 day 20 minutes') FROM persona_intro_requests;
        SELECT s12_save_thread_permissions(thread_id,'{OWNER}','{{"can_request_meetings":false}}') FROM persona_intro_requests;
        DO $$ BEGIN
          UPDATE agent_tasks SET status='accepted';
          RAISE EXCEPTION 'Expected revoked meeting refusal';
        EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
        SELECT status='proposed' FROM agent_tasks;
        """,
        "t",
    )
