"""The public card payload carries the helper's credits (and so does data.json, which is built from it)."""
from types import SimpleNamespace

from services import asks
from services import cards as cards_service
from tests.asks_support import Db, MissingTablesDb, use_db  # noqa: F401
from tests.test_asks import credit


def published_row():
    return {"id": "card-b", "handle": "bob", "status": "published", "owner_email": "bob@x.test",
            "card": {"id": "card-b", "identity": {"name": "Bob Lee"}}}


def test_the_public_payload_has_a_helped_block(monkeypatch, use_db):
    use_db(Db())
    monkeypatch.setattr(cards_service, "_select_public", lambda sb, build: SimpleNamespace(data=[published_row()]))
    monkeypatch.setattr(asks, "_credit_rows", lambda card_id: [credit("o1"), credit("o2", "cy", hidden=True)])
    card = cards_service.get_card_by_handle_public("bob")
    assert card["helped"] == {"count": 1, "items": [{"asker_handle": "ana", "asker_name": "Ana", "ask": "Need a React developer"}]}


def test_the_public_payload_still_loads_when_the_asks_tables_are_missing(monkeypatch, use_db):
    use_db(MissingTablesDb())
    monkeypatch.setattr(cards_service, "_select_public", lambda sb, build: SimpleNamespace(data=[published_row()]))
    card = cards_service.get_card_by_handle_public("bob")
    assert card["handle"] == "bob" and card["helped"] == {"count": 0, "items": []}
