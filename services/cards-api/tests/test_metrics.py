"""/metrics for Prometheus (infra/observability): counts per route template, bounded labels."""
import re

from fastapi.testclient import TestClient

import main


def _count(body: str, handler: str, status: str) -> float:
    m = re.search(
        r'^http_requests_total\{[^}]*handler="%s"[^}]*status="%s"[^}]*\} ([0-9.e+]+)$' % (re.escape(handler), status),
        body, re.M)
    return float(m.group(1)) if m else 0.0


def test_metrics_counts_a_route_and_groups_unmatched_paths():
    client = TestClient(main.app)       # no `with`: the lifespan (X bot, memory loops) stays off
    before = client.get("/metrics").text
    client.get("/health")
    client.get("/wp-login.php")         # a scanner probing a path no route matches
    client.get("/.env")
    after = client.get("/metrics")

    assert after.status_code == 200
    assert _count(after.text, "/health", "2xx") == _count(before, "/health", "2xx") + 1
    # Unmatched paths share one label value instead of minting a series per path.
    assert _count(after.text, "none", "4xx") == _count(before, "none", "4xx") + 2
    assert "wp-login" not in after.text
    # The scrape itself is not counted.
    assert 'handler="/metrics"' not in after.text


def test_metrics_is_not_in_the_public_schema():
    assert "/metrics" not in TestClient(main.app).get("/openapi.json").json()["paths"]
