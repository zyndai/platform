"""Shared fakes for the asks tests: an in-memory Supabase that knows ilike, and one whose asks tables
are "missing" the way PostgREST reports them before cards migration 0033 is applied."""
from datetime import datetime, timedelta, timezone

import pytest
from postgrest.exceptions import APIError

import config
from services import asks
from tests.fake_supabase import FakeSupabase, _Query

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
ASK_TABLES = ("asks", "ask_offers", "ask_routes")
ASK_1 = "00000000-0000-4000-8000-000000000001"
ASK_2 = "00000000-0000-4000-8000-000000000002"
OWNER = "00000000-0000-4000-8000-0000000000a1"
HELPER = "00000000-0000-4000-8000-0000000000b1"


class Query(_Query):
    def ilike(self, col, pattern):
        want = pattern.replace("\\", "").lower()
        self.filters.append(lambda r: str(r.get(col, "")).lower() == want)
        return self


class Db(FakeSupabase):
    def __init__(self, **tables):
        super().__init__(**tables)
        self.asked: list[str] = []          # table names in the order they were queried

    def table(self, name):
        self.asked.append(name)
        return Query(self, name)


class MissingTablesDb(Db):
    """Every asks table answers the way PostgREST does when the relation is not there."""

    def table(self, name):
        if name in ASK_TABLES:
            self.asked.append(name)
            query = Query(self, name)

            def boom():
                raise APIError({"code": "PGRST205", "message": f"Could not find the table 'cards.{name}' in the schema cache",
                                "details": None, "hint": None})
            query.execute = boom
            return query
        return super().table(name)


def iso(**delta) -> str:
    return (NOW - timedelta(**delta)).isoformat()


def card_row(card_id, handle, name, *, owner_email=None, owner_user_id=None, status="published", **card):
    return {"id": card_id, "handle": handle, "status": status, "owner_email": owner_email or f"{handle}@x.test",
            "owner_user_id": owner_user_id, "updated_at": "v1",
            "card": {"id": card_id, "identity": {"name": name, "headline": f"{name} headline", "avatar_url": ""}, **card}}


def ask_row(ask_id=ASK_1, card_id="card-a", *, text="Need a React developer", created_days=1, lives_days=7, **extra):
    created = NOW - timedelta(days=created_days)
    return {"id": ask_id, "card_id": card_id, "owner_user_id": OWNER, "text": text, "created_at": created.isoformat(),
            "expires_at": (created + timedelta(days=lives_days)).isoformat(), "ended_at": None, "end_reason": None,
            "outcome": None, "outcome_at": None, "outcome_prompted_at": None, **extra}


def offer_row(helper_card_id="card-b", *, ask_id=ASK_1, helper_user_id=HELPER, offer_id=None, **extra):
    return {"id": offer_id or f"offer-{helper_card_id}", "ask_id": ask_id, "helper_user_id": helper_user_id,
            "helper_card_id": helper_card_id, "connection_id": None, "channel": "dm", "created_at": iso(hours=5),
            "credited_at": None, "credit_hidden_at": None, "credit_notified_at": None, **extra}


@pytest.fixture
def use_db(monkeypatch):
    def install(db):
        monkeypatch.setattr(config, "get_supabase", lambda: db)
        return db
    return install
