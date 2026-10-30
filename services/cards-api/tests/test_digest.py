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


_real_owner_extras = digest_service._owner_extras


@pytest.fixture(autouse=True)
def default_zone(monkeypatch):
    monkeypatch.setattr(digest_service.config, "DIGEST_DEFAULT_TIMEZONE", "Asia/Kolkata")
    # The owner-only blocks read Supabase and Memory; tests that want them pass extras directly.
    monkeypatch.setattr(digest_service, "_owner_extras", lambda row, rows, now, local: {"date": "Thu, 1 Oct"})


def test_render_digest_includes_topics_posts_and_people():
    posts = {
        "summary": "Building with AI: AI is busy today.",
        "posts": [
            {"field": "working_on", "query": "Building with AI", "excerpt": "shipped agents", "url": "https://x.com/a/1",
             "platform": "x", "author": "@dev"},
            None,
        ],
    }
    people = {
        "people": [{"handle": "bob", "name": "Bob", "headline": "Founder", "url": "https://cards.zynd.ai/p/bob",
                    "why": ["Founder of an AI tools startup", "Mentions ai", "Based in Pune"]}],
        "outside": [{"name": "Pat", "title": "Recruiter", "company": "Acme", "linkedin_url": "https://linkedin.com/in/pat"}],
    }
    body = digest_service.render_digest("alice", posts, people, name="Alice Chen")
    assert "Good morning, Alice\n" in body
    assert "TODAY IN YOUR FIELD" in body
    assert "Building with AI" in body
    assert "AI is busy today" in body
    assert "https://x.com/a/1" in body
    assert "Bob" in body
    assert "https://cards.zynd.ai/p/bob" in body
    assert "  Founder of an AI tools startup · Mentions ai\n" in body          # one reason line, two reasons
    assert "Pat, Recruiter at Acme (not on Zynd yet, LinkedIn)" in body
    assert "Hide:" not in body                                         # no feedback links without a token
    assert "https://linkedin.com/in/pat" in body
    assert "working_on" not in body

    html = digest_service.render_digest_html("alice", posts, people, name="Alice Chen")
    assert "<table" in html
    assert "Good morning, Alice</div>" in html
    assert "Good morning, @alice" not in html
    assert "Today in your field" in html
    assert "AI is busy today" in html
    assert "Read on X" in html
    assert "https://x.com/a/1" in html
    assert "People for you" in html
    assert "Bob" in html and "https://cards.zynd.ai/p/bob" in html
    assert "Recruiter at Acme &middot; Not on Zynd yet" in html
    assert "https://linkedin.com/in/pat" in html
    assert "https://cards.zynd.ai/p/alice" in html
    assert "/assets/zynd-logo.png" in html
    assert "Open your dashboard" in html
    assert "#4338ca" in html
    assert "working_on" not in html
    # Blocks without data are left out entirely, with no "none today" filler.
    assert "Your card this week" not in html
    assert "From your network" not in html
    assert "none today" not in html.lower()
    assert "<script" not in html.lower()
    assert "Unsubscribe" not in html


def test_empty_sections_are_left_out():
    html = digest_service.render_digest_html("alice", {"summary": "", "posts": [None]}, {"people": [], "outside": []})
    for block in ("Your card this week", "Today in your field", "People for you", "From your network"):
        assert block not in html
    assert "Here&#x27;s what&#x27;s new in the topics you follow." in html
    assert "Open your dashboard" in html


def test_owner_blocks_render_from_extras():
    extras = {
        "date": "Mon, 26 Oct",
        "activity": {"available": True, "views": 48, "agent_hits": 112,
                     "queries": [{"query": "fintech founder Bengaluru", "count": 6}]},
        "visitors": ["Karan Shah", "Ines Duarte", "Tom Becker"],
        "to_review": 3,
        "network": {"connection_updates": [{"handle": "ada", "name": "Ada", "change": "Looking for investment", "when": "2d"}],
                    "saved_search_hits": ["New match for “fintech”: Sam"]},
        "unsubscribe_url": "https://api.test/cards/notifications/unsubscribe/tok",
        "feedback_base": "https://api.test/cards/suggestions/feedback/tok",
    }
    people = {"people": [
        {"handle": "lena", "name": "Lena Fischer", "url": "https://cards.zynd.ai/p/lena"},
        {"handle": "arjun", "name": "Arjun Mehta", "url": "https://cards.zynd.ai/p/arjun", "two_way": True, "verified": True,
         "why": ["Wants to meet founders like you", "Backs developer tools", "Based in Berlin", "Payments"]},
    ], "outside": []}
    html = digest_service.render_digest_html("alice", None, people, name="Alice", extras=extras)
    assert "Mon, 26 Oct" in html
    assert "Your card this week" in html
    assert ">48<" in html and "Profile views" in html
    assert ">112<" in html and "AI agent lookups" in html
    assert "/p/alice/edit#inbox" in html and "Facts to review" in html
    assert "fintech founder Bengaluru" in html and "&times;6" in html
    assert "Karan Shah</b> and 2 others viewed your card" in html
    assert "Wants to meet you" in html and "LinkedIn verified" in html
    # Two-way matches go first; the chip says "wants to meet you", so the reason line doesn't repeat it.
    assert html.index("Arjun Mehta") < html.index("Lena Fischer")
    assert "Backs developer tools · Based in Berlin" in html and "Payments" not in html
    assert "Wants to meet founders like you" not in html
    assert 'href="https://api.test/cards/suggestions/feedback/tok/arjun/hide"' in html
    assert 'href="https://api.test/cards/suggestions/feedback/tok/lena/not_relevant"' in html
    assert "From your network" in html and "Looking for investment &middot; 2d" in html
    assert "New match for “fintech”: Sam" in html
    assert 'href="https://api.test/cards/notifications/unsubscribe/tok"' in html
    assert "Your card had 48 views this week." in html

    d = digest_service.build_digest("alice", None, people, "Alice", extras)
    assert digest_service.digest_subject(d) == "Arjun wants to meet you too"
    body = digest_service.render_digest("alice", None, people, name="Alice", extras=extras)
    assert "48 profile views · 112 AI agent lookups · 3 facts to review" in body
    assert "Arjun Mehta (wants to meet you too)" in body
    assert "Unsubscribe: https://api.test/cards/notifications/unsubscribe/tok" in body
    assert "Hide: https://api.test/cards/suggestions/feedback/tok/arjun/hide" in body


def test_unknown_review_count_is_left_out_not_zero():
    extras = {"activity": {"available": False, "views": None, "agent_hits": None, "queries": []}}
    d = digest_service.build_digest("alice", None, None, None, extras)
    assert d["stats"] == []
    assert "Your card this week" not in digest_service.render_digest_html("alice", None, None, extras=extras)


@pytest.mark.parametrize("people, views, subject", [
    ({"people": [{"handle": "b", "name": "Bob"}], "outside": [{"name": "Pat"}]}, None, "2 people to meet today"),
    ({"people": [{"handle": "b", "name": "Bob"}], "outside": []}, None, "1 person to meet today"),
    (None, 12, "12 views on your card this week"),
    (None, None, "Your Zynd morning digest"),
])
def test_subject_names_the_best_thing_in_the_email(people, views, subject):
    extras = {"activity": {"available": views is not None, "views": views, "agent_hits": None, "queries": []}}
    assert digest_service.digest_subject(digest_service.build_digest("alice", None, people, None, extras)) == subject


def test_topics_pair_each_brief_with_its_post_by_name():
    raw = (
        "Doing research: There is a growing emphasis on research.\n\n"
        "Technical interviews: Interviews are getting harder.\n\n"
        "A paragraph with no label. It still shows."
    )
    posts = [
        {"query": "Technical interviews", "excerpt": "leetcode is back", "url": "https://x.com/a/2"},
        None,
        {"query": "Product Managers", "excerpt": "PM storytelling", "url": "https://x.com/a/3"},
    ]
    topics = digest_service.digest_topics({"summary": raw, "posts": posts})
    assert [t["topic"] for t in topics] == ["Doing research", "Technical interviews", "", "Product Managers"]
    assert topics[0]["post"] is None
    assert topics[1]["post"]["url"] == "https://x.com/a/2"
    assert topics[2]["brief"] == "A paragraph with no label. It still shows."
    assert topics[3]["brief"] == "" and topics[3]["post"]["url"] == "https://x.com/a/3"
    html = digest_service.render_digest_html("alice", {"summary": raw, "posts": posts}, None)
    assert "Doing research:" not in html
    assert "growing emphasis on research" in html


def test_clip_summary_caps_at_100_words():
    words = " ".join(f"w{i}" for i in range(1, 140))
    clipped = digest_service.clip_summary(words)
    assert len(clipped.split()) == 100
    assert clipped.startswith("w1 ")
    assert clipped.endswith("w100")
    assert digest_service.clip_summary("short note") == "short note"


def test_topic_brief_caps_at_45_words():
    words = " ".join(f"w{i}" for i in range(1, 140))
    html = digest_service.render_digest_html("alice", {"summary": f"AI: {words}", "posts": []}, None)
    assert "w45 " in html or "w45<" in html
    assert "w46" not in html


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
    monkeypatch.setattr(digest_service, "digest_people", lambda row: {"people": [], "outside": []})
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
    monkeypatch.setattr(digest_service, "digest_people", lambda row: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: None)
    monkeypatch.setattr(digest_service, "_mark_sent", lambda *a: None)

    stats = digest_service.run_digest(now=IST_7AM, dry_run=True)
    assert "Good morning, Alice</div>" in stats["previews"][0]["html"]
    assert "Good morning, @alice" not in stats["previews"][0]["html"]


def test_dry_run_does_not_send(monkeypatch):
    sent = []
    rows = [{"handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None}]
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows)
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "digest_people", lambda row: {"people": [], "outside": []})
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
    monkeypatch.setattr(digest_service, "digest_people", lambda row: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "send_smtp", lambda **kw: sent.append(kw))
    monkeypatch.setattr(digest_service, "_mark_sent", lambda handle, day, snap: None)

    stats = digest_service.run_digest(now=IST_7AM, handle="bob", dry_run=True)

    assert fetched == ["bob"]
    assert sent == []
    assert stats["sent"] == 1
    assert stats["previews"][0]["handle"] == "bob"
    assert "Good morning, @bob" in stats["previews"][0]["body"]
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
    monkeypatch.setattr(digest_service, "digest_people", lambda row: {"people": [], "outside": []})

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
    assert columns_asked == list(digest_service._DIGEST_COLUMNS)


def test_missing_prefs_columns_keep_the_timezone(monkeypatch):
    columns_asked = []
    row = {"handle": "a", "owner_email": "a@x.io", "timezone": "Asia/Kolkata"}

    def list_rows(columns, **_):
        columns_asked.append(columns)
        if "unsubscribe_token" in columns:
            raise APIError({"code": "42703", "message": "column does not exist", "details": None, "hint": None})
        return [row]

    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", list_rows)
    assert digest_service._list_digest_rows() == [row]
    assert columns_asked == list(digest_service._DIGEST_COLUMNS[:2])


def test_turned_off_digest_is_not_sent_but_still_previews(mailbox):
    off = owner("off")
    off["notification_prefs"] = {"weekly_digest": True, "morning_digest": False}
    mailbox.rows = [off, owner("on")]

    stats = digest_service.run_digest(now=IST_7AM)
    assert [m["to"] for m in mailbox.sent] == ["on@x.io"]
    assert stats["skipped_unsubscribed"] == 1

    preview = digest_service.run_digest(now=IST_7AM, handle="off", dry_run=True)
    assert preview["sent"] == 1


def test_send_carries_the_unsubscribe_link(mailbox, monkeypatch):
    monkeypatch.setattr(digest_service, "_owner_extras",
                        lambda row, rows, now, local: {"unsubscribe_url": "https://api.test/u/tok"})
    mailbox.rows = [owner("ist")]
    digest_service.run_digest(now=IST_7AM)
    assert mailbox.sent[0]["unsubscribe_url"] == "https://api.test/u/tok"
    assert "https://api.test/u/tok" in mailbox.sent[0]["html"]


def test_people_shown_are_recorded_only_after_a_real_send(mailbox, monkeypatch):
    shown = []
    monkeypatch.setattr(digest_service, "digest_people",
                        lambda row: {"people": [{"handle": "ann", "card_id": "c-ann", "two_way": True}], "outside": []})
    monkeypatch.setattr(digest_service, "_record_shown", lambda row, people: shown.append(people["people"]))
    mailbox.rows = [owner("ist")]
    digest_service.run_digest(now=IST_7AM, dry_run=True)
    assert shown == []                                   # a preview is not an impression
    digest_service.run_digest(now=IST_7AM)
    assert [p["handle"] for p in shown[0]] == ["ann"]
    assert mailbox.sent[0]["subject"].endswith("wants to meet you too")     # two-way leads the email


def test_a_suggestions_failure_still_sends_the_digest(mailbox, monkeypatch):
    monkeypatch.setattr(digest_service, "digest_people", lambda row: (_ for _ in ()).throw(RuntimeError("search down")))
    mailbox.rows = [owner("ist")]
    assert digest_service.run_digest(now=IST_7AM)["sent"] == 1


def test_owner_extras_without_owner_home_only_dates_and_links(monkeypatch):
    from services import owner_home
    monkeypatch.setattr(owner_home, "enabled", lambda: False)
    monkeypatch.setattr(digest_service.config, "API_BASE_URL", "https://api.test")
    local = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)
    extras = _real_owner_extras({"handle": "a", "owner_email": "a@x.io", "unsubscribe_token": "tok"}, [], local, local)
    assert extras == {"date": "Mon, 26 Oct", "unsubscribe_url": "https://api.test/cards/notifications/unsubscribe/tok",
                      "feedback_base": "https://api.test/cards/suggestions/feedback/tok"}


def test_owner_extras_survive_each_failing_source(monkeypatch):
    from services import owner_home, visitor_privacy, owner_notifications
    monkeypatch.setattr(owner_home, "enabled", lambda: True)
    monkeypatch.setattr(owner_home, "activity", lambda handle, now=None: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(visitor_privacy, "named_visitors", lambda h, e: {"available": True, "items": [{"name": "Ana"}, {"name": ""}]})
    monkeypatch.setattr(owner_notifications, "_network_section", lambda e, r, rows: {
        "mutual_matches": [], "saved_search_hits": [],
        "connection_updates": [{"handle": "ada", "name": "Ada", "change": "x", "approved_at": "2026-10-24T07:00:00+00:00"}]})
    monkeypatch.setattr(digest_service.config, "MEMORY_SERVICE_TOKEN", "")
    now = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)
    extras = _real_owner_extras({"handle": "a", "owner_email": "a@x.io"}, [], now, now)
    assert "activity" not in extras
    assert "to_review" not in extras
    assert extras["visitors"] == ["Ana"]
    assert extras["network"]["connection_updates"][0]["when"] == "2d"


def test_mark_people_flags_verified(monkeypatch):
    from services import trust
    me = {"handle": "alice", "id": "c-alice",
          "card": {"id": "c-alice", "identity": {"name": "Alice", "headline": "Founder of a fintech startup"}}}
    bob = {"handle": "bob", "id": "c-bob",
           "card": {"id": "c-bob", "identity": {"name": "Bob", "headline": "Seed investor"}, "connect_with": ["Founders"]}}
    cy = {"handle": "cy", "id": "c-cy", "card": {"id": "c-cy", "identity": {"name": "Cy", "headline": "Designer"}}}
    monkeypatch.setattr(trust, "verified_by_card_ids", lambda ids: {"c-bob": ["linkedin"], "c-cy": ["github"]})
    people = {"people": [{"handle": "bob", "two_way": True}, {"handle": "cy"}, {"handle": "ghost"}]}
    digest_service._mark_people(me, people, [me, bob, cy])
    bob_p, cy_p, ghost = people["people"]
    assert bob_p["two_way"] is True and bob_p["verified"] is True      # two-way comes with the suggestion
    assert not cy_p.get("two_way") and cy_p["verified"] is False
    assert "verified" not in ghost


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


def test_an_outside_person_shows_where_they_are():
    people = {"people": [], "outside": [{"name": "Pat", "title": "Venture Partner", "company": "Seed Fund",
                                         "location": "Pune, India", "linkedin_url": "https://linkedin.com/in/pat"}]}
    assert "Pat, Venture Partner at Seed Fund · Pune, India (not on Zynd yet, LinkedIn)" in \
        digest_service.render_digest("alice", None, people)
    assert "Venture Partner at Seed Fund · Pune, India &middot; Not on Zynd yet" in \
        digest_service.render_digest_html("alice", None, people)
