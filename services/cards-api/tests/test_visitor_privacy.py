from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import config
from api import visitors
from services import visitor_privacy as privacy

UID = '11111111-1111-4111-8111-111111111111'
VID = '22222222-2222-4222-8222-222222222222'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, 'SUPABASE_DB_SCHEMA', 'cards')
    monkeypatch.setattr(config, 'SUPABASE_URL', 'https://database.test')
    monkeypatch.setattr(config, 'FEATURE_S04_EVENTS', True)
    principal = SimpleNamespace(sub=UID, iss='https://database.test/auth/v1', email='alice@example.com', user_metadata={'name': 'Alice'})
    def verify(auth):
        if auth != 'Bearer owner':
            raise HTTPException(401, 'Unauthorized')
        return principal
    monkeypatch.setattr(visitors, '_principal', verify)
    monkeypatch.setattr(visitors.events, 'rate_limited', lambda key: False)
    app = FastAPI()
    app.include_router(visitors.router, prefix='/cards')
    return TestClient(app), principal


AUTH = {'Authorization': 'Bearer owner'}


def test_privacy_requires_auth(client):
    client, _ = client
    assert client.get('/cards/mine/visitor-privacy').status_code == 401
    assert client.patch('/cards/mine/visitor-privacy', json={'anonymous_mode': False}).status_code == 401


def test_missing_preference_is_anonymous(monkeypatch):
    sb = MagicMock()
    q = sb.table.return_value
    q.select.return_value = q
    q.eq.return_value = q
    q.limit.return_value = q
    q.execute.return_value.data = []
    monkeypatch.setattr(config, 'get_supabase', lambda: sb)
    assert privacy.preference(UID) == {'anonymous_mode': True}
    q.eq.assert_called_once_with('user_id', UID)


def test_identity_is_derived_from_verified_token_not_body(client, monkeypatch):
    client, _ = client
    op = MagicMock(return_value={'anonymous_mode': False})
    monkeypatch.setattr(privacy, 'rpc', op)
    assert client.patch('/cards/mine/visitor-privacy', json={'anonymous_mode': False}, headers=AUTH).status_code == 200
    op.assert_called_once_with('s10_set_visitor_privacy', {'p_user': UID, 'p_anonymous': False, 'p_name': 'Alice'})
    assert client.patch('/cards/mine/visitor-privacy', json={'anonymous_mode': False, 'user_id': VID}, headers=AUTH).status_code == 422


def test_foreign_issuer_cannot_collide_with_local_user_uuid(client, monkeypatch):
    client, principal = client
    principal.iss = 'https://foreign.test/auth/v1'
    op = MagicMock()
    monkeypatch.setattr(privacy, 'rpc', op)
    assert client.patch('/cards/mine/visitor-privacy', json={'anonymous_mode': False}, headers=AUTH).status_code == 403
    op.assert_not_called()


def test_anonymous_visit_never_records_identity(client, monkeypatch):
    client, _ = client
    op = MagicMock()
    monkeypatch.setattr(privacy, 'rpc', op)
    assert client.post('/cards/by-handle/alice/visit', json={'visit_id': VID}).status_code == 204
    op.assert_not_called()


def test_named_visit_uses_verified_name_and_user(client, monkeypatch):
    client, _ = client
    op = MagicMock(return_value=True)
    monkeypatch.setattr(privacy, 'rpc', op)
    response = client.post('/cards/by-handle/bob/visit', json={'visit_id': VID}, headers=AUTH)
    assert response.json() == {'recorded': True}
    op.assert_called_once_with('s10_record_named_visit', {'p_id': VID, 'p_user': UID, 'p_email': 'alice@example.com', 'p_handle': 'bob', 'p_name': 'Alice'})
    assert client.post('/cards/by-handle/bob/visit', json={'visit_id': VID, 'name': 'Impersonated'}, headers=AUTH).status_code == 422


def test_email_never_becomes_a_display_name():
    assert privacy.display_name(SimpleNamespace(user_metadata={'name': 'secret@example.com'})) == 'Zynd member'


def test_named_visitors_are_owner_bound_and_unavailable_is_not_empty(monkeypatch):
    op = MagicMock(return_value=[{'name': 'Bob', 'visited_at': 'today', 'visits': 2}])
    monkeypatch.setattr(privacy, 'rpc', op)
    assert privacy.named_visitors('alice', 'alice@example.com')['items'][0]['name'] == 'Bob'
    op.assert_called_once_with('s10_named_visitors', {'p_handle': 'alice', 'p_owner_email': 'alice@example.com'})
    op.side_effect = HTTPException(503, 'Missing migrations')
    assert privacy.named_visitors('alice', 'alice@example.com') == {'available': False, 'items': []}
