"""Integration tests for shareable page hosting (/me/pages + public /pages/{slug})."""
import pytest

from app.config import settings

pytestmark = pytest.mark.integration

AUTH = {"Authorization": f"Bearer {settings.dev_bearer_token}"}


async def test_publish_returns_url_and_serves_publicly(client):
    r = await client.post("/me/pages", headers=AUTH, json={
        "content": "# Hello\n\nThis is **bold** and a [link](https://zynd.ai).",
        "title": "My Page", "format": "markdown",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    slug = body["slug"]
    assert body["url"].endswith(f"/pages/{slug}")
    assert body["title"] == "My Page"

    # Public render — no auth header — markdown converted to HTML.
    page = await client.get(f"/pages/{slug}")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    html = page.text
    assert "<h1" in html and "Hello" in html
    assert "<strong>bold</strong>" in html
    assert 'href="https://zynd.ai"' in html


async def test_full_html_document_served_verbatim(client):
    doc = "<!doctype html><html><head><title>Raw</title></head><body><p id='x'>hi</p></body></html>"
    r = await client.post("/me/pages", headers=AUTH, json={"content": doc, "format": "html"})
    slug = r.json()["slug"]
    page = await client.get(f"/pages/{slug}")
    assert page.text == doc  # author-supplied full page respected as-is


async def test_html_fragment_is_wrapped(client):
    r = await client.post("/me/pages", headers=AUTH, json={
        "content": "<h2>Fragment</h2><p>body</p>", "format": "html", "title": "Frag",
    })
    slug = r.json()["slug"]
    html = (await client.get(f"/pages/{slug}")).text
    assert "<!doctype html>" in html.lower()   # wrapped in the template
    assert "<h2>Fragment</h2>" in html
    assert "<title>Frag</title>" in html


async def test_private_page_is_not_served(client):
    r = await client.post("/me/pages", headers=AUTH, json={
        "content": "secret", "format": "html", "visibility": "private",
    })
    slug = r.json()["slug"]
    page = await client.get(f"/pages/{slug}")
    assert page.status_code == 404


async def test_unknown_slug_is_404(client):
    assert (await client.get("/pages/does-not-exist")).status_code == 404


async def test_served_page_is_sandboxed(client):
    """Hosted HTML/JS must be served with a sandbox CSP so it can't reach the API origin."""
    slug = (await client.post("/me/pages", headers=AUTH,
                              json={"content": "<b>hi</b>", "format": "html"})).json()["slug"]
    page = await client.get(f"/pages/{slug}")
    csp = page.headers.get("content-security-policy", "")
    assert "sandbox" in csp
    assert page.headers.get("x-content-type-options") == "nosniff"
    assert page.headers.get("x-frame-options") == "DENY"


async def test_list_pages_newest_first(client):
    await client.post("/me/pages", headers=AUTH, json={"content": "one", "title": "One"})
    await client.post("/me/pages", headers=AUTH, json={"content": "two", "title": "Two"})
    r = await client.get("/me/pages", headers=AUTH)
    assert r.status_code == 200
    pages = r.json()
    assert [p["title"] for p in pages][:2] == ["Two", "One"]
    assert all("content" not in p for p in pages)  # list is metadata-only


async def test_update_and_delete(client):
    slug = (await client.post("/me/pages", headers=AUTH,
                              json={"content": "v1", "title": "T"})).json()["slug"]

    upd = await client.patch(f"/me/pages/{slug}", headers=AUTH,
                             json={"title": "T2", "content": "<b>v2</b>"})
    assert upd.status_code == 200 and upd.json()["title"] == "T2"
    assert "<b>v2</b>" in (await client.get(f"/pages/{slug}")).text

    dele = await client.delete(f"/me/pages/{slug}", headers=AUTH)
    assert dele.status_code == 200 and dele.json()["success"] is True
    assert (await client.get(f"/pages/{slug}")).status_code == 404


async def test_publish_requires_auth(client):
    r = await client.post("/me/pages", json={"content": "x"})
    assert r.status_code == 401


async def test_update_unknown_slug_404(client):
    r = await client.patch("/me/pages/nope", headers=AUTH, json={"title": "x"})
    assert r.status_code == 404
