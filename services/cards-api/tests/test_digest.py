from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import digest as digest_service


def test_render_digest_includes_summary_posts_and_people():
    posts = {
        "summary": "AI is busy today.",
        "posts": [
            {"field": "working_on", "query": "Building with AI", "excerpt": "shipped agents", "url": "https://x.com/a/1"},
            None,
        ],
    }
    people = {
        "people": [{"handle": "bob", "name": "Bob", "headline": "Founder", "url": "https://zynd.ai/p/bob"}],
        "outside": [{"name": "Pat", "title": "Recruiter", "company": "Acme", "linkedin_url": "https://linkedin.com/in/pat"}],
    }
    body = digest_service.render_digest("alice", posts, people)
    assert "AI is busy today" in body
    assert "https://x.com/a/1" in body
    assert "Bob" in body
    assert "https://zynd.ai/p/bob" in body
    assert "Pat" in body
    assert "https://linkedin.com/in/pat" in body
    assert "@alice" in body


def test_run_digest_skips_no_email_and_already_sent(monkeypatch):
    sent = []
    rows = [
        {"handle": "no-mail", "owner_email": None, "suggested_posts": None},
        {"handle": "done", "owner_email": "done@x.io", "suggested_posts": {"digest_sent_on": "2026-10-01"}},
        {"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None},
    ]
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "get_suggested_people", lambda h: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: sent.append(kw))
    monkeypatch.setattr(digest_service, "_mark_sent", lambda handle, day, snap: None)

    stats = digest_service.run_digest(today="2026-10-01")

    assert stats["sent"] == 1
    assert stats["skipped_no_email"] == 1
    assert stats["skipped_already"] == 1
    assert sent[0]["to"] == "alice@x.io"
    assert sent[0]["subject"].startswith("Your Zynd morning digest")


def test_dry_run_does_not_send(monkeypatch):
    sent = []
    rows = [{"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None}]
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "get_suggested_people", lambda h: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: sent.append(kw))
    monkeypatch.setattr(digest_service, "_mark_sent", lambda *a: (_ for _ in ()).throw(AssertionError("no mark")))

    stats = digest_service.run_digest(today="2026-10-01", dry_run=True)

    assert stats["sent"] == 1
    assert sent == []


def test_run_digest_handle_only_processes_that_card(monkeypatch):
    sent = []
    fetched = []
    rows = [
        {"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None},
        {"handle": "bob", "owner_email": "bob@x.io", "suggested_posts": None},
    ]
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: fetched.append(h) or {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "get_suggested_people", lambda h: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: sent.append(kw))
    monkeypatch.setattr(digest_service, "_mark_sent", lambda handle, day, snap: None)

    stats = digest_service.run_digest(today="2026-10-01", handle="bob", dry_run=True)

    assert fetched == ["bob"]
    assert sent == []
    assert stats["sent"] == 1
    assert stats["previews"][0]["handle"] == "bob"
    assert "Morning digest for @bob" in stats["previews"][0]["body"]


def test_run_digest_unknown_handle_is_empty(monkeypatch):
    monkeypatch.setattr(
        digest_service.cards_service,
        "list_published_rows",
        lambda **_k: [{"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None}],
    )
    stats = digest_service.run_digest(today="2026-10-01", handle="nobody", dry_run=True)
    assert stats["sent"] == 0
    assert stats["not_found"] is True


def test_internal_route_requires_cron_secret(monkeypatch):
    from api import internal as internal_api

    monkeypatch.setattr(internal_api.config, "CRON_SECRET", "sekrit")
    monkeypatch.setattr(internal_api, "run_digest", lambda **_k: {"sent": 0})
    app = FastAPI()
    app.include_router(internal_api.router, prefix="/internal")
    client = TestClient(app)

    assert client.post("/internal/morning-digest").status_code == 401
    assert client.post("/internal/morning-digest", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.post("/internal/morning-digest", headers={"Authorization": "Bearer sekrit"})
    assert ok.status_code == 200
    assert ok.json()["sent"] == 0

    seen = {}
    monkeypatch.setattr(internal_api, "run_digest", lambda **kw: seen.update(kw) or {"sent": 1, "previews": []})
    one = client.post(
        "/internal/morning-digest?dry_run=true&handle=atmegabuzz",
        headers={"Authorization": "Bearer sekrit"},
    )
    assert one.status_code == 200
    assert seen["dry_run"] is True
    assert seen["handle"] == "atmegabuzz"


def test_internal_route_503_when_cron_secret_unset(monkeypatch):
    from api import internal as internal_api

    monkeypatch.setattr(internal_api.config, "CRON_SECRET", "")
    app = FastAPI()
    app.include_router(internal_api.router, prefix="/internal")
    client = TestClient(app)
    assert client.post("/internal/morning-digest", headers={"Authorization": "Bearer x"}).status_code == 503


def test_clear_suggested_posts_nulls_all_or_one(monkeypatch):
    class Q:
        def __init__(self, data):
            self.data = data
            self.ops = []

        def table(self, name):
            self.ops.append(("table", name))
            return self

        def update(self, payload):
            self.ops.append(("update", payload))
            return self

        def eq(self, col, val):
            self.ops.append(("eq", col, val))
            return self

        def neq(self, col, val):
            self.ops.append(("neq", col, val))
            return self

        def execute(self):
            return type("R", (), {"data": self.data})()

    all_q = Q([{"id": "1"}, {"id": "2"}])
    monkeypatch.setattr(digest_service.config, "get_supabase", lambda: all_q)
    stats = digest_service.clear_suggested_posts()
    assert stats == {"cleared": 2}
    assert ("update", {"suggested_posts": None}) in all_q.ops
    assert ("neq", "id", "") in all_q.ops

    one_q = Q([{"handle": "saraffa13"}])
    monkeypatch.setattr(digest_service.config, "get_supabase", lambda: one_q)
    stats = digest_service.clear_suggested_posts(handle="@Saraffa13")
    assert stats == {"cleared": 1}
    assert ("eq", "handle", "saraffa13") in one_q.ops

    miss = Q([])
    monkeypatch.setattr(digest_service.config, "get_supabase", lambda: miss)
    stats = digest_service.clear_suggested_posts(handle="nobody")
    assert stats == {"cleared": 0, "not_found": True}


def test_clear_suggested_posts_route_requires_cron_secret(monkeypatch):
    from api import internal as internal_api

    monkeypatch.setattr(internal_api.config, "CRON_SECRET", "sekrit")
    seen = {}
    monkeypatch.setattr(
        internal_api, "clear_suggested_posts", lambda **kw: seen.update(kw) or {"cleared": 3}
    )
    app = FastAPI()
    app.include_router(internal_api.router, prefix="/internal")
    client = TestClient(app)

    assert client.post("/internal/clear-suggested-posts").status_code == 401
    all_ = client.post(
        "/internal/clear-suggested-posts",
        headers={"Authorization": "Bearer sekrit"},
    )
    assert all_.status_code == 200
    assert all_.json() == {"cleared": 3}
    assert seen["handle"] is None

    one = client.post(
        "/internal/clear-suggested-posts?handle=saraffa13",
        headers={"Authorization": "Bearer sekrit"},
    )
    assert one.status_code == 200
    assert seen["handle"] == "saraffa13"
