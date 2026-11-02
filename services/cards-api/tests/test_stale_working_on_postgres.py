"""Every cards-api write path to Working on, replayed against cards migration 0035 on a disposable
local Postgres: the trigger must stamp each one that changes the list and no other.

STALE_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5547/postgres pytest tests/test_stale_working_on_postgres.py
A scratch database is created and dropped per run. Like tests/test_s10_postgres.py, the table is
the minimal subset the functions touch (no pgvector); the full history is packages/db's job
(packages/db/test/cards-stale-working-on-sql.test.ts).
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest

from models.card import AgentProfileCard, Beacon
from services import stale_signals

SERVER = os.getenv("STALE_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not SERVER, reason="STALE_TEST_DATABASE_URL (disposable local Postgres) not set")
MIGRATIONS = Path(__file__).resolve().parents[3] / "packages/db/cards/migrations"
OWNER = "alice@example.com"

BASE = """
DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE SCHEMA cards;
CREATE TABLE cards.agent_profile_cards(
  id text PRIMARY KEY, handle text UNIQUE, status text NOT NULL DEFAULT 'published', owner_email text,
  card jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  embedding text, merged_into text);
"""


def _psql(dsn: str, statement: str) -> str:
    result = subprocess.run(["psql", dsn, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
                            input=statement, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture(scope="module")
def db():
    url = urlparse(SERVER)
    assert url.hostname in {"127.0.0.1", "localhost"}, "tests require a disposable local Postgres"
    name = f"cards_stale_{os.getpid()}_{int(time.time())}"
    _psql(SERVER, f"CREATE DATABASE {name};")
    dsn = url._replace(path=f"/{name}").geturl()
    try:
        _psql(dsn, BASE + "".join((MIGRATIONS / f).read_text() for f in
                                  ("0011_s10_owner_operations.sql", "0032_companion_devices.sql", "0035_stale_working_on.sql")))
        yield lambda statement: _psql(dsn, statement)
    finally:
        _psql(SERVER, f"DROP DATABASE IF EXISTS {name} WITH (FORCE);")


def _j(value) -> str:
    return "$j$" + json.dumps(value) + "$j$::jsonb"


def _stored(db) -> tuple[datetime | None, AgentProfileCard]:
    raw = json.loads(db("SELECT json_build_object('stamp', working_on_updated_at, 'card', card) "
                        "FROM cards.agent_profile_cards WHERE id='c1';"))
    stamp = datetime.fromisoformat(raw["stamp"]) if raw["stamp"] else None
    return stamp, AgentProfileCard.model_validate(raw["card"])


def _age(db) -> datetime:
    db("UPDATE cards.agent_profile_cards SET working_on_updated_at = now() - interval '200 days' WHERE id='c1';")
    stamp, read = _stored(db)
    assert stale_signals.working_on_is_stale(read) is True
    return stamp


def _publish(db, card: AgentProfileCard) -> None:
    """services/cards.py insert_card: PostgREST upsert on id, setting the payload's columns."""
    db(f"""INSERT INTO cards.agent_profile_cards(id,handle,status,owner_email,card,embedding)
           VALUES('c1','alice','published','{OWNER}',{_j(card.model_dump(mode="json"))},NULL)
           ON CONFLICT (id) DO UPDATE SET handle=EXCLUDED.handle, status=EXCLUDED.status,
             owner_email=EXCLUDED.owner_email, card=EXCLUDED.card, embedding=EXCLUDED.embedding;""")


def _full_card_update(db, card: AgentProfileCard) -> None:
    """services/cards.py update_card (editor PATCH) and services/beacons.py save_beacon."""
    db(f"UPDATE cards.agent_profile_cards SET card={_j(card.model_dump(mode='json'))}, updated_at=now(), "
       f"embedding=NULL WHERE handle='alice';")


def _rpc(db, call: str) -> None:
    db(f"SELECT {call};")


def test_every_write_path(db):
    # #given onboarding publishes a card with a Working on list
    _publish(db, AgentProfileCard(id="c1", handle="alice", working_on=["Zynd Cards"]))
    stamp, read = _stored(db)
    assert stamp is not None and read.working_on_updated_at == stamp
    assert stale_signals.working_on_is_stale(read) is False

    # republishing the same list (re-onboard) keeps the stamp; a new list restamps
    aged = _age(db)
    _publish(db, read)
    assert _stored(db)[0] == aged
    _publish(db, read.model_copy(update={"working_on": ["Agent search"]}))
    assert _stored(db)[0] > aged

    # the editor's full-card PATCH: from a card read earlier (stale mirror), unchanged list
    aged = _age(db)
    _, read = _stored(db)
    _full_card_update(db, read.model_copy(update={"summary": "New about", "working_on_updated_at": None}))
    stamp, read = _stored(db)
    assert stamp == aged and read.working_on_updated_at == aged and read.summary == "New about"
    _full_card_update(db, read.model_copy(update={"working_on": ["Agent search", "Evals"]}))
    assert _stored(db)[0] > aged

    # a beacon publish rewrites the card JSON but not the list
    aged = _age(db)
    _, read = _stored(db)
    now = datetime.now(timezone.utc)
    _full_card_update(db, read.model_copy(update={"beacon": Beacon(text="Hiring", created_at=now, expires_at=now + timedelta(days=7))}))
    assert _stored(db)[0] == aged

    # the editor's section save (s10_save_section): another section no, the Working on section yes
    working = _stored(db)[1].working_on
    _rpc(db, f"cards.s10_save_section('{OWNER}','alice',{_j({'summary': 'Again'})},{_j({'summary': 'New about'})})")
    assert _stored(db)[0] == aged
    _rpc(db, f"cards.s10_save_section('{OWNER}','alice',{_j({'working_on': ['Evals']})},{_j({'working_on': working})})")
    assert _stored(db)[0] > aged

    # the browser extension (companion_save_fields)
    aged = _age(db)
    _rpc(db, f"cards.companion_save_fields('{OWNER}','alice',{_j({'working_on': ['Evals', 'Clip']})},{_j({'working_on': ['Evals']})})")
    assert _stored(db)[0] > aged

    # memory refresh (s10_patch_system_fields) and visibility changes leave it alone
    aged = _age(db)
    _rpc(db, f"cards.s10_patch_system_fields('alice',{_j({'zynd_memory': []})})")
    _rpc(db, f"cards.s10_visibility('{OWNER}','alice',false)")
    _rpc(db, f"cards.s10_visibility('{OWNER}','alice',true)")
    assert _stored(db)[0] == aged

    # the owner's confirm (services/stale_signals.confirm_working_on) sets only the column
    confirmed = datetime.now(timezone.utc).replace(microsecond=0)
    db(f"UPDATE cards.agent_profile_cards SET working_on_updated_at='{confirmed.isoformat()}' WHERE id='c1';")
    stamp, read = _stored(db)
    assert stamp == confirmed and read.working_on_updated_at == confirmed
    assert read.working_on == ["Evals", "Clip"]
    assert stale_signals.working_on_is_stale(read) is False


def test_legacy_row_stays_unknown(db):
    # #given a row written before 0035 (no stamp), simulated with the trigger off
    db("ALTER TABLE cards.agent_profile_cards DISABLE TRIGGER agent_profile_cards_working_on_stamp;")
    db(f"INSERT INTO cards.agent_profile_cards(id,handle,owner_email,card) VALUES('legacy','legacy','{OWNER}',"
       f"{_j({'id': 'legacy', 'working_on': ['Something old']})});")
    db("ALTER TABLE cards.agent_profile_cards ENABLE TRIGGER agent_profile_cards_working_on_stamp;")
    # #when something other than the list is saved
    _rpc(db, f"cards.s10_save_section('{OWNER}','legacy',{_j({'summary': 'Hi'})},{_j({'summary': ''})})")
    # #then it is still unknown, and unknown is never stale
    raw = json.loads(db("SELECT json_build_object('stamp', working_on_updated_at, 'card', card) "
                        "FROM cards.agent_profile_cards WHERE id='legacy';"))
    assert raw["stamp"] is None and "working_on_updated_at" not in raw["card"]
    assert stale_signals.working_on_is_stale(AgentProfileCard.model_validate(raw["card"])) is False
