import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.mark.parametrize("origin", ["http://localhost:3002", "http://127.0.0.1:3002"])
def test_cards_local_origins_can_preflight_authenticated_refresh(origin):
    client = TestClient(app)
    response = client.options("/cards/mine/recaps", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    # CORS permits the browser request; it does not bypass the route's existing session check.
    response = client.post("/cards/mine/recaps", headers={"Origin": origin}, json={"period": "2026-10", "refresh": True})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://unrelated.example", "http://127.0.0.1:3003", "http://localhost:3002.attacker.example"])
def test_unrelated_origins_are_not_allowed(origin):
    response = TestClient(app).options("/cards/mine/recaps", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
