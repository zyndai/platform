from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfoNotFoundError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from services import digest as digest_service

# 07:00 IST on 2026-10-01: the digest hour for owners on the default zone.
IST_7AM = datetime(2026, 10, 1, 1, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def default_zone(monkeypatch):
    monkeypatch.setattr(digest_service.config, "DIGEST_DEFAULT_TIMEZONE", "Asia/Kolkata")


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
    body = digest_service.render_digest("alice", posts, people, name="Alice Chen")
    assert "AI is busy today" in body
    assert "https://x.com/a/1" in body
    assert "Bob" in body
    assert "https://zynd.ai/p/bob" in body
    assert "Pat" in body
    assert "https://linkedin.com/in/pat" in body
    assert "working_on" not in body

    html = digest_service.render_digest_html("alice", posts, people, name="Alice Chen")
    assert "<table" in html
    assert "AI is busy today" in html
    assert "https://x.com/a/1" in html
    assert "Bob" in html
    assert "https://zynd.ai/p/bob" in html
    assert "Pat" in html
    assert "https://linkedin.com/in/pat" in html
    assert "zynd.ai/p/alice" in html
    assert "Good morning, Alice Chen!" in html
    assert "Good morning, @alice" not in html
    assert "Curated Posts" in html
    assert "People on Zynd" in html
    assert "Outside Network" in html
    assert "View Zynd Profile" in html
    assert "Connect on LinkedIn" in html
    assert "Working On" not in html
    assert "Can Help With" not in html
    assert "Connect With" not in html
    assert "Love Talking About" not in html
    assert "Founder" in html
    assert "Recruiter at Acme" in html
    assert "#554ac0" in html
    assert "#faf8ff" in html
    assert "tailwind" not in html.lower()
    assert "<script" not in html.lower()
    assert "googleapis.com" not in html
    assert "Unsubscribe" not in html
    assert "Edition #" not in html


def test_digest_summary_drops_topic_labels():
    raw = (
        "Doing research: There is a growing emphasis on research.\n\n"
        "Technical interviews: Interviews are getting harder.\n\n"
        "Product Managers: PMs are navigating PR and storytelling."
    )
    text = digest_service.digest_summary(raw)
    assert "Doing research:" not in text
    assert "Technical interviews:" not in text
    assert "Product Managers:" not in text
    assert "growing emphasis on research" in text
    assert "Interviews are getting harder" in text
    html = digest_service.render_digest_html("alice", {"summary": raw, "posts": []}, None)
    assert "Doing research" not in html
    assert "growing emphasis on research" in html


def test_clip_summary_caps_at_100_words():
    words = " ".join(f"w{i}" for i in range(1, 140))
    clipped = digest_service.clip_summary(words)
    assert len(clipped.split()) == 100
    assert clipped.startswith("w1 ")
    assert clipped.endswith("w100")
    assert digest_service.clip_summary("short note") == "short note"
    html = digest_service.render_digest_html("alice", {"summary": words, "posts": []}, None)
    assert "w101" not in html
    assert "w100" in html


def test_post_excerpt_caps_at_30_words():
    words = " ".join(f"p{i}" for i in range(1, 50))
    posts = {"posts": [{"excerpt": words, "url": "https://x.com/a/1"}]}
    body = digest_service.render_digest("alice", posts, None)
    html = digest_service.render_digest_html("alice", posts, None)
    assert "p31" not in body
    assert "p30" in body
    assert "p31" not in html
    assert "p30" in html
    assert len(digest_service.clip_summary(words, 30).split()) == 30


def test_render_digest_html_escapes_content():
    posts = {
        "summary": "<script>alert(1)</script>",
        "posts": [{"field": "working_on", "excerpt": "a < b", "url": "https://x.com/a/1"}],
    }
    html = digest_service.render_digest_html("alice", posts, None)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &lt; b" in html


def test_send_smtp_attaches_html(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(digest_service.config, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(digest_service.config, "SMTP_USER", "from@zynd.ai")
    monkeypatch.setattr(digest_service.config, "SMTP_PASSWORD", "x")
    monkeypatch.setattr(digest_service.config, "SMTP_FROM", "from@zynd.ai")
    monkeypatch.setattr(digest_service.config, "SMTP_PORT", 587)
    monkeypatch.setattr(digest_service.smtplib, "SMTP", FakeSMTP)

    digest_service.send_smtp(to="a@x.io", subject="s", body="plain", html="<table>hi</table>")
    msg = sent[0]
    assert msg.get_content_type() == "multipart/alternative"
    parts = list(msg.iter_parts())
    types = {p.get_content_type() for p in parts}
    assert "text/plain" in types
    assert "text/html" in types


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

    stats = digest_service.run_digest(now=IST_7AM)

    assert stats["sent"] == 1
    assert stats["skipped_no_email"] == 1
    assert stats["skipped_already"] == 1
    assert sent[0]["to"] == "alice@x.io"
    assert sent[0]["subject"].startswith("Your Zynd morning digest")
    assert sent[0]["html"]
    assert "<table" in sent[0]["html"]


def test_run_digest_greets_with_identity_name(monkeypatch):
    rows = [{
        "handle": "alice",
        "owner_email": "alice@x.io",
        "suggested_posts": None,
        "card": {"identity": {"name": "Alice Chen"}},
    }]
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "get_suggested_people", lambda h: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: None)
    monkeypatch.setattr(digest_service, "_mark_sent", lambda *a: None)

    stats = digest_service.run_digest(now=IST_7AM, dry_run=True)
    assert "Good morning, Alice Chen!" in stats["previews"][0]["html"]
    assert "Good morning, @alice" not in stats["previews"][0]["html"]


def test_dry_run_does_not_send(monkeypatch):
    sent = []
    rows = [{"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None}]
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "get_suggested_people", lambda h: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: sent.append(kw))
    monkeypatch.setattr(digest_service, "_mark_sent", lambda *a: (_ for _ in ()).throw(AssertionError("no mark")))

    stats = digest_service.run_digest(now=IST_7AM, dry_run=True)

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

    stats = digest_service.run_digest(now=IST_7AM, handle="bob", dry_run=True)

    assert fetched == ["bob"]
    assert sent == []
    assert stats["sent"] == 1
    assert stats["previews"][0]["handle"] == "bob"
    assert "Morning digest for @bob" in stats["previews"][0]["body"]
    assert "<table" in stats["previews"][0]["html"]
    assert "@bob" in stats["previews"][0]["html"]


def test_run_digest_unknown_handle_is_empty(monkeypatch):
    monkeypatch.setattr(
        digest_service.cards_service,
        "list_published_rows",
        lambda **_k: [{"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None}],
    )
    stats = digest_service.run_digest(now=IST_7AM, handle="nobody", dry_run=True)
    assert stats["sent"] == 0
    assert stats["not_found"] is True


def owner(handle, tz=None):
    return {"handle": handle, "owner_email": f"{handle}@x.io", "suggested_posts": None, "timezone": tz}


@pytest.fixture
def mailbox(monkeypatch):
    """Stubs everything run_digest touches. `events` records the order of mark and send."""
    box = SimpleNamespace(rows=[], sent=[], events=[])
    monkeypatch.setattr(digest_service, "_list_digest_rows", lambda: box.rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "get_suggested_people", lambda h: {"people": [], "outside": []})

    def mark(handle, day, snap):
        box.events.append(("mark", handle, day))
        for row in box.rows:
            if row["handle"] == handle:
                row["suggested_posts"] = {**(snap or {}), "digest_sent_on": day}

    def send(**kw):
        box.events.append(("send", kw["to"]))
        box.sent.append(kw)

    monkeypatch.setattr(digest_service, "_mark_sent", mark)
    monkeypatch.setattr(digest_service, "send_smtp", send)
    return box


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize("now, due", [
    # IST is UTC+5:30, Kathmandu +5:45, PDT -7, AEDT +11 (all on these October dates).
    (utc(2026, 10, 23, 1, 30), {"ist", "kathmandu"}),  # 07:00 IST; 07:15 in Kathmandu
    (utc(2026, 10, 23, 14, 0), {"la"}),                # 07:00 PDT
    (utc(2026, 10, 22, 20, 0), {"sydney"}),            # 07:00 AEDT on the 23rd
    (utc(2026, 10, 23, 5, 0), set()),                  # 10:30 IST: window is over; everyone else is asleep
])
def test_each_owner_gets_the_digest_at_7am_their_time(mailbox, now, due):
    mailbox.rows = [owner("ist"), owner("la", "America/Los_Angeles"),
                    owner("sydney", "Australia/Sydney"), owner("kathmandu", "Asia/Kathmandu")]

    stats = digest_service.run_digest(now=now)

    assert {m["to"].split("@")[0] for m in mailbox.sent} == due
    assert stats["sent"] == len(due)
    assert stats["skipped_not_due"] == 4 - len(due)


@pytest.mark.parametrize("minutes_after_7am_ist, due", [
    (-1, False),    # 06:59
    (0, True),      # 07:00
    (179, True),    # 09:59: a late GitHub tick still sends
    (180, False),   # 10:00: too late to call it a morning digest
])
def test_send_window_is_7_to_10_local(mailbox, minutes_after_7am_ist, due):
    mailbox.rows = [owner("a")]

    stats = digest_service.run_digest(now=IST_7AM + timedelta(minutes=minutes_after_7am_ist))

    assert stats["sent"] == int(due)


def test_window_follows_daylight_saving(mailbox):
    # New York falls back on 2026-11-01 at 06:00 UTC. A fixed UTC-4 would make 11:00 UTC "07:00".
    mailbox.rows = [owner("ny", "America/New_York")]

    assert digest_service.run_digest(now=utc(2026, 10, 31, 11, 0))["sent"] == 1   # 07:00 EDT
    assert digest_service.run_digest(now=utc(2026, 11, 1, 11, 0))["sent"] == 0    # 06:00 EST
    assert digest_service.run_digest(now=utc(2026, 11, 1, 12, 0))["sent"] == 1    # 07:00 EST


def test_digest_day_is_the_owners_local_date_not_utc(mailbox):
    # 20:00 UTC on the 22nd is already the 23rd in Sydney.
    mailbox.rows = [owner("sydney", "Australia/Sydney")]

    digest_service.run_digest(now=utc(2026, 10, 22, 20, 0))

    assert ("mark", "sydney", "2026-10-23") in mailbox.events


def test_repeated_ticks_send_once_per_local_day(mailbox):
    mailbox.rows = [owner("a")]

    first = digest_service.run_digest(now=IST_7AM)
    again = digest_service.run_digest(now=IST_7AM + timedelta(minutes=30))
    tomorrow = digest_service.run_digest(now=IST_7AM + timedelta(days=1))

    assert (first["sent"], again["sent"], tomorrow["sent"]) == (1, 0, 1)
    assert again["skipped_already"] == 1
    assert [e[2] for e in mailbox.events if e[0] == "mark"] == ["2026-10-01", "2026-10-02"]


@pytest.mark.parametrize("stored", [None, "", "Not/AZone", "../etc/passwd"])
def test_missing_or_unusable_timezone_uses_the_default_zone(mailbox, stored):
    mailbox.rows = [owner("a", stored)]

    assert digest_service.run_digest(now=IST_7AM)["sent"] == 1


def test_ignore_schedule_sends_outside_the_window(mailbox):
    mailbox.rows = [owner("a")]
    noon = IST_7AM + timedelta(hours=5)

    assert digest_service.run_digest(now=noon)["skipped_not_due"] == 1
    assert digest_service.run_digest(now=noon, ignore_schedule=True)["sent"] == 1
    # Still once per local day.
    assert digest_service.run_digest(now=noon, ignore_schedule=True)["skipped_already"] == 1


def test_handle_preview_works_outside_the_window(mailbox):
    mailbox.rows = [owner("a"), owner("b")]

    stats = digest_service.run_digest(now=IST_7AM + timedelta(hours=5), handle="b", dry_run=True)

    assert [p["handle"] for p in stats["previews"]] == ["b"]
    assert mailbox.events == []


def test_day_is_claimed_before_the_email_goes_out(mailbox):
    mailbox.rows = [owner("a")]

    digest_service.run_digest(now=IST_7AM)

    assert [e[0] for e in mailbox.events] == ["mark", "send"]


def test_failed_send_is_not_repeated_on_the_next_tick(mailbox, monkeypatch):
    mailbox.rows = [owner("a")]
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: (_ for _ in ()).throw(RuntimeError("smtp down")))

    first = digest_service.run_digest(now=IST_7AM)
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: mailbox.sent.append(kw))
    second = digest_service.run_digest(now=IST_7AM + timedelta(minutes=30))

    assert (first["sent"], first["errors"]) == (0, 1)
    assert (second["sent"], second["skipped_already"]) == (0, 1)
    assert mailbox.sent == []


def test_failure_before_the_claim_leaves_the_day_open(mailbox, monkeypatch):
    mailbox.rows = [owner("a")]
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: (_ for _ in ()).throw(RuntimeError("llm down")))

    failed = digest_service.run_digest(now=IST_7AM)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    retried = digest_service.run_digest(now=IST_7AM + timedelta(minutes=30))

    assert (failed["sent"], failed["errors"]) == (0, 1)
    assert retried["sent"] == 1


def test_missing_timezone_column_falls_back_to_the_default_zone(monkeypatch):
    columns_asked = []
    row = {"handle": "a", "owner_email": "a@x.io"}

    def list_rows(columns, **_):
        columns_asked.append(columns)
        if "timezone" in columns:
            raise APIError({"code": "42703", "message": "column agent_profile_cards.timezone does not exist",
                            "details": None, "hint": None})
        return [row]

    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", list_rows)

    assert digest_service._list_digest_rows() == [row]
    assert columns_asked == ["handle,owner_email,suggested_posts,card,timezone",
                             "handle,owner_email,suggested_posts,card"]


def test_other_database_errors_are_not_swallowed(monkeypatch):
    def list_rows(columns, **_):
        raise APIError({"code": "57014", "message": "canceling statement due to statement timeout",
                        "details": None, "hint": None})

    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", list_rows)

    with pytest.raises(APIError):
        digest_service._list_digest_rows()


@pytest.mark.parametrize("name", [None, "", "   ", "Not/AZone", "../etc/passwd", "/etc/passwd", "America"])
def test_valid_zone_rejects_unusable_names(name):
    assert digest_service.valid_zone(name) is None


def test_valid_zone_accepts_iana_names():
    assert digest_service.valid_zone(" Asia/Kolkata ").key == "Asia/Kolkata"


def test_bad_default_zone_fails_loudly(monkeypatch):
    monkeypatch.setattr(digest_service.config, "DIGEST_DEFAULT_TIMEZONE", "Nowhere/Land")

    with pytest.raises(ZoneInfoNotFoundError):
        digest_service.resolve_zone(None)


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
    assert seen["ignore_schedule"] is False

    everyone = client.post(
        "/internal/morning-digest?ignore_schedule=true",
        headers={"Authorization": "Bearer sekrit"},
    )
    assert everyone.status_code == 200
    assert seen["ignore_schedule"] is True


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
