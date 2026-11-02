"""Asks in the morning digest: the sections, escaping, and that "already said" is recorded only after
the email actually went out (and never for a preview)."""
from datetime import datetime, timezone

from services import asks
from services import digest as digest_service

IST_7AM = datetime(2026, 10, 1, 1, 30, tzinfo=timezone.utc)
EVIL = '<script>alert(1)</script> & "quotes"'


def section(**kw):
    base = {"routed": [], "prompts": [], "credits": [], "marks": {"routes": ["a1"], "prompts": ["p1"], "credits": ["o1"]}}
    return {"asks": {**base, **kw}}


def render(extras):
    return (digest_service.render_digest("alice", None, None, name="Alice", extras=extras),
            digest_service.render_digest_html("alice", None, None, name="Alice", extras=extras))


def test_routed_asks_get_their_own_section_linking_to_the_feed():
    text, html = render(section(routed=[{"ask_id": "a1", "text": "Need a React developer", "asker_handle": "bob", "asker_name": "Bob"}]))
    assert "ASKS YOU COULD HELP WITH" in text and "Need a React developer" in text
    assert "/feed?filter=asks" in text and "/feed?filter=asks" in html
    assert "Asks you could help with" in html and "I can help" in html


def test_the_follow_up_lines_are_one_each():
    text, html = render(section(prompts=[{"ask_id": "p1", "text": "x"}],
                                credits=[{"asker_name": "Bob", "asker_handle": "bob", "ask": "Need a React developer"}]))
    assert "Your ask ended. Did you find help?" in text and "/home" in text
    assert 'Bob credited you for helping with "Need a React developer"' in text
    assert "Your ask ended" in html and "Bob credited you" in html


def test_nothing_about_asks_when_there_is_nothing_to_say():
    text, html = render({})
    assert "ASKS" not in text and "Asks you could help with" not in html and "About your asks" not in html
    text, html = render(section())
    assert "ASKS" not in text and "About your asks" not in html


def test_everything_from_other_people_is_escaped_in_the_html():
    _, html = render(section(
        routed=[{"ask_id": "a1", "text": EVIL, "asker_handle": "bob", "asker_name": EVIL}],
        credits=[{"asker_name": EVIL, "asker_handle": "bob", "ask": EVIL}]))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def rows():
    return [{"id": "card-a", "handle": "alice", "owner_email": "alice@x.io", "suggested_posts": None, "card": {}}]


def wire(monkeypatch, *, marks_to=None, send=None):
    monkeypatch.setattr(digest_service.cards_service, "list_published_rows", lambda **_k: rows())
    monkeypatch.setattr(digest_service, "get_suggested_posts", lambda h: {"summary": "s", "posts": []})
    monkeypatch.setattr(digest_service, "digest_people", lambda row: {"people": [], "outside": []})
    monkeypatch.setattr(digest_service, "_record_shown", lambda *a: None)
    monkeypatch.setattr(digest_service, "_mark_sent", lambda *a: None)
    monkeypatch.setattr(digest_service, "_owner_extras", lambda row, rows, now, local: {"date": "x", **section(
        routed=[{"ask_id": "a1", "text": "Need help", "asker_handle": "bob", "asker_name": "Bob"}])})
    monkeypatch.setattr(digest_service, "send_smtp", send or (lambda **kw: None))
    monkeypatch.setattr(asks, "mark_digest_sent", lambda row, marks, now: marks_to.append((row["id"], marks)))


def test_the_asks_are_marked_as_said_after_a_successful_send(monkeypatch):
    marked = []
    wire(monkeypatch, marks_to=marked)
    stats = digest_service.run_digest(now=IST_7AM)
    assert stats["sent"] == 1
    assert marked == [("card-a", {"routes": ["a1"], "prompts": ["p1"], "credits": ["o1"]})]


def test_a_failed_send_marks_nothing_so_the_asks_come_again_tomorrow(monkeypatch):
    marked = []

    def failing(**kw):
        raise RuntimeError("smtp down")
    wire(monkeypatch, marks_to=marked, send=failing)
    stats = digest_service.run_digest(now=IST_7AM)
    assert stats["errors"] == 1 and marked == []


def test_a_preview_shows_the_asks_but_marks_nothing(monkeypatch):
    marked = []
    wire(monkeypatch, marks_to=marked)
    stats = digest_service.run_digest(now=IST_7AM, dry_run=True)
    (preview,) = stats["previews"]
    assert "ASKS YOU COULD HELP WITH" in preview["body"] and "Need help" in preview["html"]
    assert marked == []
