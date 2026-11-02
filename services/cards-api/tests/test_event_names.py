"""Every event name the API emits must be one events.emit() accepts.

emit() silently drops a name that is in neither ALLOWED_EVENTS nor SERVER_EVENTS, so a name left
out of both is never recorded and nothing fails. ask_offer and ask_outcome were lost that way.
"""
import re
from pathlib import Path

from services import events

_ROOT = Path(__file__).resolve().parent.parent
_EMIT = re.compile(r"\b_?emit\(\s*[\"']([a-z_]+)[\"']")


def _emitted_names() -> dict[str, str]:
    found = {}
    for folder in ("services", "api"):
        for path in (_ROOT / folder).rglob("*.py"):
            for name in _EMIT.findall(path.read_text(encoding="utf-8")):
                found.setdefault(name, str(path.relative_to(_ROOT)))
    return found


def test_scan_finds_the_emit_calls():
    names = _emitted_names()
    assert {"feed_view", "feed_reply", "ask_offer"} <= set(names)


def test_every_emitted_event_is_accepted():
    accepted = events.ALLOWED_EVENTS | events.SERVER_EVENTS
    dropped = {name: where for name, where in _emitted_names().items() if name not in accepted}
    assert not dropped, f"emit() would silently drop: {dropped}"


def test_asks_events_cannot_be_forged_by_the_public_endpoint():
    for name in ("ask_offer", "ask_outcome", "ask_published"):
        assert name in events.SERVER_EVENTS and name not in events.ALLOWED_EVENTS
