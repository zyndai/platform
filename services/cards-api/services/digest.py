"""Morning digest: each card owner's week, topic news, people and network updates, by SMTP."""
from __future__ import annotations

import asyncio
import html as html_lib
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postgrest.exceptions import APIError

import config
from services import cards as cards_service
from services.suggested_people import get_suggested_people
from services.suggested_posts import get_suggested_posts

logger = logging.getLogger(__name__)

# The digest goes out at 07:00 in each owner's own timezone. The workflow ticks every 30
# minutes (so half-hour zones like IST land on time), but GitHub delays and sometimes skips
# scheduled runs, so a tick up to DIGEST_GRACE_HOURS after 07:00 local still sends it.
DIGEST_LOCAL_HOUR = 7
DIGEST_GRACE_HOURS = 3

MAX_TOPICS = 4
BRIEF_WORDS = 45
EXCERPT_WORDS = 30

# Light palette from the Cards owner home (/home). Inline only: Gmail drops <link> CSS and
# most of <style>, so the one <style> block below is a phone-width enhancement, nothing more.
_BG = "#f4f5f7"
_WHITE = "#ffffff"
_LINE = "#e5e7eb"
_INK = "#111827"
_BODY = "#374151"
_MUTED = "#6b7280"
_ACCENT = "#4338ca"
_WORDMARK_ACCENT = "#6366f1"
_LAV, _LAV_INK = "#eef0ff", "#3730a3"
_GRAY = "#f3f4f6"
_GREEN, _GREEN_INK = "#ecfdf3", "#067647"
_STAR, _STAR_INK = "#fef6e0", "#b54708"
_LI = "#0a66c2"
_X = "#111827"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
_WORDMARK_FONT = "'Chakra Petch','Space Grotesk'," + _FONT

# Phones: drop the outer frame and move each row's button under its text.
_MOBILE_CSS = (
    "@media (max-width:480px){"
    "td.o{padding:0!important}table.s{border-radius:0!important}td.i{padding:20px 16px!important}"
    "td.m,td.a{display:block!important;width:auto!important}td.m{padding-bottom:8px!important}"
    "td.a{text-align:left!important;padding:0 16px 16px 64px!important;border-top:0!important}}"
)


def clip_summary(text: str, limit: int = 100) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit])


def topic_briefs(summary: str | None) -> list[tuple[str, str]]:
    """Split the stitched summary ("query: blurb" paragraphs) back into (topic, brief) pairs.
    A paragraph without a short topic label comes back with an empty topic."""
    out = []
    for para in (summary or "").split("\n\n"):
        para = para.strip()
        if not para:
            continue
        head, sep, rest = para.partition(": ")
        if sep and rest.strip() and len(head.split()) <= 6 and "." not in head:
            out.append((head.strip(), rest.strip()))
        else:
            out.append(("", para))
    return out


def digest_topics(posts: dict | None) -> list[dict]:
    """One entry per topic the owner follows: its brief and the post picked for it today.
    Posts carry the query they were picked for, so they pair with briefs by name."""
    posts = posts or {}
    by_query: dict[str, dict] = {}
    loose = []
    for slot in posts.get("posts") or []:
        if not slot:
            continue
        key = (slot.get("query") or "").strip().lower()
        if key and key not in by_query:
            by_query[key] = slot
        else:
            loose.append(slot)
    topics = []
    for head, brief in topic_briefs(posts.get("summary")):
        post = by_query.pop(head.lower(), None) if head else None
        topics.append({"topic": head, "brief": clip_summary(brief, BRIEF_WORDS), "post": post})
    for slot in [*by_query.values(), *loose]:
        topics.append({"topic": (slot.get("query") or "").strip(), "brief": "", "post": slot})
    return topics[:MAX_TOPICS]


def _first_name(name: str | None, handle: str = "") -> str:
    n = (name or "").strip()
    return n.split()[0] if n else (f"@{handle}" if handle else "")


def _identity_name(card) -> str:
    if not isinstance(card, dict):
        return ""
    ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    return (ident.get("name") or "").strip()


def _esc(s) -> str:
    return html_lib.escape(str(s or ""), quote=True)


def _base() -> str:
    return (config.SITE_BASE_URL or "https://zynd.ai").rstrip("/")


def _card_url(handle: str) -> str:
    return f"{_base()}/p/{handle}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _post_platform(slot: dict) -> str:
    platform = (slot.get("platform") or "").lower()
    if platform in ("x", "linkedin"):
        return platform
    u = (slot.get("url") or "").lower()
    if "linkedin.com" in u:
        return "linkedin"
    return "x" if ("x.com" in u or "twitter.com" in u) else ""


def build_digest(handle: str, posts: dict | None, people: dict | None, name: str | None = None,
                 extras: dict | None = None) -> dict:
    """Everything both renderers show, with empty blocks already dropped."""
    people = people or {}
    extras = extras or {}
    zynd = sorted(people.get("people") or [], key=lambda p: not p.get("two_way"))
    outside = list(people.get("outside") or [])
    activity = extras.get("activity") if isinstance(extras.get("activity"), dict) else {}
    network = extras.get("network") or {}
    stats = []
    if activity.get("available"):
        if activity.get("views") is not None:
            stats.append((activity["views"], "Profile views", ""))
        if activity.get("agent_hits") is not None:
            stats.append((activity["agent_hits"], "AI agent lookups", ""))
    if extras.get("to_review") is not None:
        stats.append((extras["to_review"], "Facts to review", f"{_base()}/p/{handle}/edit#inbox"))
    return {
        "handle": handle,
        "first": _first_name(name, handle),
        "date": extras.get("date") or "",
        "stats": stats,
        "views": activity.get("views") if activity.get("available") else None,
        "queries": [q for q in (activity.get("queries") or []) if (q.get("query") or "").strip()][:3],
        "visitors": [v for v in (extras.get("visitors") or []) if v][:10],
        "topics": digest_topics(posts),
        "people": zynd,
        "outside": outside,
        "updates": list(network.get("connection_updates") or []),
        "search_hits": list(network.get("saved_search_hits") or []),
        "unsubscribe_url": extras.get("unsubscribe_url") or "",
    }


def _two_way_person(d: dict) -> dict | None:
    return next((p for p in d["people"] if p.get("two_way")), None)


def digest_subject(d: dict) -> str:
    match = _two_way_person(d)
    if match:
        return f"{_first_name(match.get('name'), match.get('handle') or '')} wants to meet you too"
    n = len(d["people"]) + len(d["outside"])
    if n:
        return f"{n} {_plural(n, 'person', 'people')} to meet today"
    if d["views"]:
        return f"{d['views']} {_plural(d['views'], 'view', 'views')} on your card this week"
    return "Your Zynd morning digest"


def _intro(d: dict) -> tuple[str, str]:
    """The line under the greeting, as (text, html)."""
    parts_text, parts_html = [], []
    if d["views"] is not None:
        line = f"Your card had {d['views']} {_plural(d['views'], 'view', 'views')} this week."
        parts_text.append(line)
        parts_html.append(_esc(line))
    n = len(d["people"]) + len(d["outside"])
    if n:
        line = f"{n} {_plural(n, 'person matches', 'people match')} what you're looking for"
        match = _two_way_person(d)
        if match:
            first = _first_name(match.get("name"), match.get("handle") or "")
            parts_text.append(f"{line}, and {first} wants to meet you too.")
            parts_html.append(f"{_esc(line)}, and <b style=\"font-weight:600;color:{_INK}\">{_esc(first)}</b> wants to meet you too.")
        else:
            parts_text.append(line + ".")
            parts_html.append(_esc(line) + ".")
    if not parts_text:
        line = "Here's what's new in the topics you follow."
        return line, _esc(line)
    return " ".join(parts_text), " ".join(parts_html)


def _preheader(d: dict) -> str:
    parts = []
    if d["views"]:
        parts.append(f"{d['views']} {_plural(d['views'], 'view', 'views')} on your card this week")
    names = [t["topic"] for t in d["topics"] if t["topic"]][:3]
    if names:
        parts.append("news in " + ", ".join(names))
    n = len(d["people"]) + len(d["outside"])
    if n:
        parts.append(f"{n} {_plural(n, 'person', 'people')} to meet")
    if not parts:
        return "Your Zynd morning digest."
    line = ", ".join(parts) + "."
    return line[0].upper() + line[1:]


# ── plain text ──

def render_digest(handle: str, posts: dict | None, people: dict | None, name: str | None = None,
                  extras: dict | None = None) -> str:
    d = build_digest(handle, posts, people, name, extras)
    lines = [f"Good morning, {d['first']}", _intro(d)[0]]
    if d["stats"] or d["queries"] or d["visitors"]:
        lines += ["", "YOUR CARD THIS WEEK"]
        if d["stats"]:
            lines.append(" · ".join(f"{n} {label[0].lower() + label[1:] if label[1:2].islower() else label}"
                                    for n, label, _ in d["stats"]))
        if d["queries"]:
            lines.append("Searches that found you: " + ", ".join(f"\"{q['query']}\" ({q.get('count', 1)})" for q in d["queries"]))
        if d["visitors"]:
            lines.append(_visitors_line(d["visitors"]))
    if d["topics"]:
        lines += ["", "TODAY IN YOUR FIELD"]
        for t in d["topics"]:
            if t["topic"]:
                lines.append(t["topic"])
            if t["brief"]:
                lines.append(t["brief"])
            post = t["post"]
            if post:
                author = (post.get("author") or "").strip()
                excerpt = clip_summary((post.get("excerpt") or "").strip(), EXCERPT_WORDS)
                lines.append(f"- {author + ': ' if author else ''}{excerpt}")
                if post.get("url"):
                    lines.append(f"  {post['url']}")
            lines.append("")
        lines.pop()
    if d["people"] or d["outside"]:
        lines += ["", "PEOPLE FOR YOU"]
        for p in d["people"]:
            label = p.get("name") or p.get("handle") or ""
            headline = (p.get("headline") or "").strip()
            lines.append(f"- {label}" + (f", {headline}" if headline else "") + (" (wants to meet you too)" if p.get("two_way") else ""))
            if p.get("url"):
                lines.append(f"  {p['url']}")
        for p in d["outside"]:
            role = _outside_role(p)
            lines.append(f"- {p.get('name') or ''}" + (f", {role}" if role else "") + " (LinkedIn)")
            if p.get("linkedin_url"):
                lines.append(f"  {p['linkedin_url']}")
    if d["updates"] or d["search_hits"]:
        lines += ["", "FROM YOUR NETWORK"]
        lines += [f"- {u.get('name') or u.get('handle')}: {u.get('change')}" for u in d["updates"]]
        lines += [f"- {hit}" for hit in d["search_hits"]]
    lines += ["", f"Open your dashboard: {_base()}/home", f"Your public card: {_card_url(handle)}"]
    if d["unsubscribe_url"]:
        lines.append(f"Unsubscribe: {d['unsubscribe_url']}")
    return "\n".join(lines).strip() + "\n"


def _visitors_line(names: list[str]) -> str:
    rest = len(names) - 1
    return names[0] + (f" and {rest} {_plural(rest, 'other', 'others')}" if rest else "") + " viewed your card"


def _outside_role(p: dict) -> str:
    title, company = (p.get("title") or "").strip(), (p.get("company") or "").strip()
    return f"{title} at {company}" if title and company else (title or company)


# ── html ──

def _table(rows: str, style: str = "", cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"{c} '
            f'style="border-collapse:separate;{style}">{rows}</table>')


def _initials(name: str) -> str:
    words = (name or "?").split()[:2]
    return _esc("".join(w[0] for w in words).upper() or "?")


def _avatar(name: str, *, zynd: bool = True, size: int = 36, photo: str = "") -> str:
    if photo.startswith("https://"):
        return (f'<img src="{_esc(photo)}" width="{size}" height="{size}" alt="" '
                f'style="display:block;width:{size}px;height:{size}px;border-radius:{size // 2}px;border:0;object-fit:cover">')
    bg, fg = (_LAV, _LAV_INK) if zynd else (_GRAY, _MUTED)
    return (f'<div style="width:{size}px;height:{size}px;border-radius:{size // 2}px;background:{bg};color:{fg};'
            f'font:600 {13 if size >= 32 else 10}px/{size}px {_FONT};text-align:center">{_initials(name)}</div>')


def _tile(glyph: str, bg: str, fg: str, size: int = 13) -> str:
    return (f'<div style="width:36px;height:36px;border-radius:8px;background:{bg};color:{fg};'
            f'font:700 {size}px/36px Arial,sans-serif;text-align:center">{glyph}</div>')


def _mark(platform: str) -> str:
    bg, glyph = (_LI, "in") if platform == "linkedin" else (_X, "X")
    return (f'<span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:{bg};color:{_WHITE};'
            f'font:700 10px/18px Arial,sans-serif;text-align:center;vertical-align:-4px">{glyph}</span>')


def _chip(text_html: str, bg: str, fg: str) -> str:
    return (f'<span style="display:inline-block;margin:4px 4px 0 0;padding:0 8px;border-radius:4px;background:{bg};'
            f'color:{fg};font:600 11px/20px {_FONT};white-space:nowrap">{text_html}</span>')


def _action(url: str, label: str) -> str:
    return (f'<a href="{_esc(url)}" style="display:inline-block;padding:0 12px;border:1px solid {_LINE};border-radius:6px;'
            f'color:{_INK};text-decoration:none;font:600 12px/28px {_FONT};white-space:nowrap">{_esc(label)}</a>')


def _label(text: str) -> str:
    return (f'<div style="font:600 11px/16px {_FONT};letter-spacing:.08em;text-transform:uppercase;'
            f'color:{_MUTED};padding:24px 0 8px">{_esc(text)}</div>')


def _box(rows: str) -> str:
    return _table(rows, f"background:{_WHITE};border:1px solid {_LINE};border-radius:10px")


def _row(i: int, visual: str, title: str, sub: str, url: str, action: str, extra: str = "") -> str:
    """The one list row: [36px visual] [title, sub, extra] [button]. Divider above all but the first."""
    top = f"border-top:1px solid {_LINE};" if i else ""
    text = (f'<div style="font:600 14px/20px {_FONT};color:{_INK}">{title}</div>'
            + (f'<div style="font:400 13px/20px {_FONT};color:{_MUTED}">{sub}</div>' if sub else "")
            + extra)
    inner = _table(f'<tr><td width="36" valign="top">{visual}</td>'
                   f'<td valign="top" style="padding-left:12px">{text}</td></tr>')
    button = _action(url, action) if url else ""
    return (f'<tr><td class="m" valign="top" style="{top}padding:16px 0 16px 16px">{inner}</td>'
            f'<td class="a" width="1" align="right" valign="top" style="{top}padding:16px 16px 16px 12px">{button}</td></tr>')


def _card_week_html(d: dict) -> str:
    if not (d["stats"] or d["queries"] or d["visitors"]):
        return ""
    span = max(len(d["stats"]), 1)
    rows = ""
    if d["stats"]:
        width = 100 // len(d["stats"])
        cells = ""
        for i, (n, label, url) in enumerate(d["stats"]):
            divider = f"border-left:1px solid {_LINE};" if i else ""
            number = (f'<a href="{_esc(url)}" style="color:{_ACCENT};text-decoration:none">{n}</a>'
                      if url and n else str(n))
            cells += (f'<td valign="top" width="{width}%" style="{divider}padding:16px">'
                      f'<div style="font:600 22px/28px {_FONT};color:{_ACCENT if url and n else _INK}">{number}</div>'
                      f'<div style="font:400 12px/18px {_FONT};color:{_MUTED}">{_esc(label)}</div></td>')
        rows += f"<tr>{cells}</tr>"
    if d["queries"]:
        top = f"border-top:1px solid {_LINE};" if rows else ""
        chips = "".join(
            _chip(f'{_esc(clip_summary(q["query"], 8))} <span style="color:{_MUTED};font-weight:400">&times;{int(q.get("count") or 1)}</span>', _GRAY, _BODY)
            for q in d["queries"])
        rows += (f'<tr><td colspan="{span}" style="{top}padding:12px 16px">'
                 f'<div style="font:400 12px/18px {_FONT};color:{_MUTED}">Searches that found you</div><div>{chips}</div></td></tr>')
    if d["visitors"]:
        top = f"border-top:1px solid {_LINE};" if rows else ""
        names = d["visitors"]
        faces = "".join(f'<td width="28" valign="middle">{_avatar(n, size=24)}</td>' for n in names[:3])
        rest = len(names) - 1
        line = (f'<b style="font-weight:600;color:{_INK}">{_esc(names[0])}</b>'
                + (f" and {rest} {_plural(rest, 'other', 'others')}" if rest else "") + " viewed your card")
        rows += (f'<tr><td colspan="{span}" style="{top}padding:12px 16px">'
                 + _table(f'<tr>{faces}<td valign="middle" style="padding-left:4px;font:400 13px/20px {_FONT};color:{_BODY}">{line}</td></tr>')
                 + "</td></tr>")
    return _label("Your card this week") + _box(rows)


def _topics_html(d: dict) -> str:
    if not d["topics"]:
        return ""
    rows = ""
    for i, t in enumerate(d["topics"]):
        top = f"border-top:1px solid {_LINE};" if i else ""
        body = ""
        if t["topic"]:
            body += f'<div style="font:600 14px/20px {_FONT};color:{_INK}">{_esc(t["topic"])}</div>'
        if t["brief"]:
            body += f'<div style="font:400 13px/20px {_FONT};color:{_BODY};padding-top:4px">{_esc(t["brief"])}</div>'
        post = t["post"]
        if post:
            platform = _post_platform(post)
            author = (post.get("author") or "").strip()
            excerpt = clip_summary((post.get("excerpt") or "").strip(), EXCERPT_WORDS)
            url = post.get("url") or ""
            source = {"x": "X", "linkedin": "LinkedIn"}.get(platform, "")
            byline = (f'<div style="font:600 12px/18px {_FONT};color:{_INK};padding-bottom:4px">'
                      f'{_mark(platform) + "&nbsp; " if platform else ""}{_esc(author)}</div>') if (author or platform) else ""
            link = (f'<div style="padding-top:8px"><a href="{_esc(url)}" style="font:600 12px/18px {_FONT};color:{_ACCENT};'
                    f'text-decoration:none">Read{" on " + source if source else ""} &rarr;</a></div>') if url else ""
            body += (f'<div style="margin-top:{12 if body else 0}px;padding:12px;background:{_BG};border-radius:8px">'
                     f'{byline}<div style="font:400 13px/20px {_FONT};color:{_BODY}">{_esc(excerpt)}</div>{link}</div>')
        rows += f'<tr><td style="{top}padding:16px">{body}</td></tr>'
    return _label("Today in your field") + _box(rows)


_VERIFIED = (f'&nbsp;<span title="LinkedIn verified" style="display:inline-block;width:14px;height:14px;border-radius:7px;'
             f'background:{_LI};color:{_WHITE};font:700 9px/14px Arial,sans-serif;text-align:center;vertical-align:1px">&#10003;</span>')


def _people_html(d: dict) -> str:
    rows = []
    for p in d["people"]:
        pname = p.get("name") or p.get("handle") or ""
        sub = _esc(p.get("headline") or "")
        if p.get("location"):
            sub += (" &middot; " if sub else "") + _esc(p["location"])
        tags = [w for words in (p.get("matched_fields") or {}).values() for w in words]
        tags = list(dict.fromkeys(tags))[: 2 if p.get("two_way") else 3]
        chips = (_chip("&#8646; Wants to meet you", _GREEN, _GREEN_INK) if p.get("two_way") else "") \
            + "".join(_chip(_esc(t), _GRAY, _BODY) for t in tags)
        rows.append(_row(len(rows), _avatar(pname, photo=p.get("avatar_url") or ""),
                         _esc(pname) + (_VERIFIED if p.get("verified") else ""), sub,
                         p.get("url") or "", "View", f"<div>{chips}</div>" if chips else ""))
    for p in d["outside"]:
        pname = p.get("name") or ""
        role = _outside_role(p)
        sub = (_esc(role) + " &middot; " if role else "") + "on LinkedIn"
        rows.append(_row(len(rows), _avatar(pname, zynd=False), _esc(pname), sub, p.get("linkedin_url") or "", "LinkedIn"))
    return _label("People for you") + _box("".join(rows)) if rows else ""


def _network_html(d: dict) -> str:
    rows = []
    for u in d["updates"]:
        uname = u.get("name") or u.get("handle") or ""
        sub = _esc(u.get("change") or "") + (f" &middot; {_esc(u['when'])}" if u.get("when") else "")
        rows.append(_row(len(rows), _avatar(uname), _esc(uname), sub, _card_url(u["handle"]) if u.get("handle") else "", "View"))
    for hit in d["search_hits"]:
        rows.append(_row(len(rows), _tile("&#9733;", _STAR, _STAR_INK, 15), _esc(hit), "Saved search", f"{_base()}/home", "See"))
    return _label("From your network") + _box("".join(rows)) if rows else ""


def render_digest_html(handle: str, posts: dict | None, people: dict | None, name: str | None = None,
                       extras: dict | None = None) -> str:
    d = build_digest(handle, posts, people, name, extras)
    base = _base()
    card = _card_url(handle)
    header = _table(
        f'<tr><td width="28" valign="middle"><img src="{_esc(base)}/assets/zynd-logo.png" width="28" height="28" alt="Zynd" '
        f'style="display:block;width:28px;height:28px;border:0"></td>'
        f'<td valign="middle" style="padding-left:8px;font:700 16px/20px {_WORDMARK_FONT};letter-spacing:.02em;'
        f'text-transform:uppercase;color:{_INK}">Zynd<span style="color:{_WORDMARK_ACCENT}">Cards</span></td>'
        f'<td align="right" valign="middle" style="font:400 12px/20px {_FONT};color:{_MUTED}">{_esc(d["date"])}</td></tr>')
    cta = _table(
        f'<tr><td style="padding-top:24px"><a href="{_esc(base)}/home" style="display:block;padding:0 16px;border-radius:8px;'
        f'background:{_ACCENT};color:{_WHITE};text-decoration:none;text-align:center;font:600 14px/44px {_FONT}">'
        f"Open your dashboard</a></td></tr>")
    unsubscribe = (f' &nbsp;&middot;&nbsp; <a href="{_esc(d["unsubscribe_url"])}" style="color:{_MUTED}">Unsubscribe</a>'
                   if d["unsubscribe_url"] else "")
    footer = _table(
        f'<tr><td align="center" style="padding:16px 8px 0;font:400 12px/18px {_FONT};color:{_MUTED}">'
        f'You get this because you own <a href="{_esc(card)}" style="color:{_MUTED}">{_esc(card.split("://", 1)[-1])}</a><br>'
        f'<a href="{_esc(base)}/home" style="color:{_MUTED}">Email settings</a>{unsubscribe}</td></tr>',
        "max-width:600px")
    main = _table(
        f'<tr><td class="i" style="padding:24px">{header}'
        f'<div style="font:600 20px/28px {_FONT};color:{_INK};padding-top:24px">Good morning, {_esc(d["first"])}</div>'
        f'<div style="font:400 14px/22px {_FONT};color:{_BODY};padding-top:4px">{_intro(d)[1]}</div>'
        f"{_card_week_html(d)}{_topics_html(d)}{_people_html(d)}{_network_html(d)}{cta}</td></tr>",
        f"max-width:600px;background:{_WHITE};border-radius:12px", cls="s")
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@700&display=swap">'
        f"<style>{_MOBILE_CSS}</style></head>"
        f'<body style="margin:0;padding:0;background:{_BG}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_esc(_preheader(d))}</div>'
        + _table(f'<tr><td class="o" align="center" style="padding:24px 16px">{main}{footer}</td></tr>', f"background:{_BG}")
        + "</body></html>"
    )


def send_smtp(*, to: str, subject: str, body: str, html: str | None = None, unsubscribe_url: str | None = None) -> None:
    if not config.SMTP_HOST or not config.SMTP_USER:
        raise RuntimeError("SMTP_HOST / SMTP_USER not set")
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()
        if config.SMTP_PASSWORD:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)


def valid_zone(name: str | None) -> ZoneInfo | None:
    """The IANA zone for `name`, or None when it is empty or unknown."""
    try:
        return ZoneInfo((name or "").strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def resolve_zone(name: str | None) -> ZoneInfo:
    """The owner's zone, or the default for owners who have not stored a usable one.

    The default is not caught: a bad DIGEST_DEFAULT_TIMEZONE should fail the run loudly
    rather than quietly send every digest at the wrong hour.
    """
    return valid_zone(name) or ZoneInfo(config.DIGEST_DEFAULT_TIMEZONE)


def _in_send_window(local: datetime) -> bool:
    return DIGEST_LOCAL_HOUR <= local.hour < DIGEST_LOCAL_HOUR + DIGEST_GRACE_HOURS


# Newest schema first. 42703 (undefined column) means cards-api is deployed ahead of a
# migration, or still on the pre-cards schema: step down a level rather than send no digest.
_DIGEST_COLUMNS = (
    "id,handle,owner_email,owner_user_id,suggested_posts,card,timezone,notification_prefs,unsubscribe_token",
    "handle,owner_email,suggested_posts,card,timezone",
    "handle,owner_email,suggested_posts,card",
)


def _list_digest_rows() -> list[dict]:
    for columns in _DIGEST_COLUMNS[:-1]:
        try:
            return cards_service.list_published_rows(columns=columns)
        except APIError as exc:
            if str(exc.code) != "42703":
                raise
            logger.warning("digest: missing column in %s, trying fewer", columns)
    logger.warning("digest: timezone column missing, using %s for everyone", config.DIGEST_DEFAULT_TIMEZONE)
    return cards_service.list_published_rows(columns=_DIGEST_COLUMNS[-1])


def _ago(iso: str | None, now: datetime) -> str:
    try:
        days = (now - datetime.fromisoformat(str(iso).replace("Z", "+00:00"))).days
    except (TypeError, ValueError):
        return ""
    return "today" if days <= 0 else f"{days}d"


def _owner_extras(row: dict, rows: list[dict], now: datetime, local: datetime) -> dict:
    """The owner-only parts: card activity, visitors, facts to review, network news, and the
    two-way and verified marks on suggested people. Each part is best effort: a failure drops
    that block from the email, never the email."""
    handle = row.get("handle") or ""
    email = (row.get("owner_email") or "").strip()
    extras: dict = {"date": f"{local:%a}, {local.day} {local:%b}"}
    if row.get("unsubscribe_token"):
        extras["unsubscribe_url"] = (f"{config.API_BASE_URL.rstrip('/')}/cards/notifications/unsubscribe/"
                                     f"{row['unsubscribe_token']}")
    from services import owner_home
    if not owner_home.enabled():
        return extras
    try:
        extras["activity"] = owner_home.activity(handle, now)
    except Exception as exc:  # noqa: BLE001
        logger.info("digest activity failed handle=%s err=%s", handle, exc)
    try:
        from services.visitor_privacy import named_visitors
        visitors = named_visitors(handle, email)
        extras["visitors"] = [(v.get("name") or "").strip() for v in visitors.get("items") or [] if (v.get("name") or "").strip()]
    except Exception as exc:  # noqa: BLE001
        logger.info("digest visitors failed handle=%s err=%s", handle, exc)
    if config.MEMORY_SERVICE_TOKEN and email:
        try:
            from services import zynd_mcp
            extras["to_review"] = len(asyncio.run(zynd_mcp.suggested_facts(email)))
        except Exception as exc:  # noqa: BLE001 — unknown is not zero: the tile is left out
            logger.info("digest review count failed handle=%s err=%s", handle, exc)
    try:
        from services.owner_notifications import _network_section
        network = _network_section(email.lower(), row, rows)
        if network:
            for u in network.get("connection_updates") or []:
                u["when"] = _ago(u.get("approved_at"), now)
            extras["network"] = network
    except Exception as exc:  # noqa: BLE001
        logger.info("digest network failed handle=%s err=%s", handle, exc)
    return extras


def _mark_people(row: dict, people: dict, rows: list[dict]) -> None:
    """Flag suggested people who want to meet someone like the owner, and verified ones."""
    from services import trust, two_way
    from services.digest_network import _card

    by_handle = {r.get("handle"): r for r in rows if r.get("handle")}
    me = _card(row) if row.get("card") else None
    mine = two_way.kinds_of(me) if me else set()
    found = [p for p in people.get("people") or [] if p.get("handle") in by_handle]
    for p in found:
        other = _card(by_handle[p["handle"]]) if mine else None
        if other:
            p["two_way"] = two_way.two_way_match(mine, other)
    verified = trust.verified_by_card_ids([by_handle[p["handle"]].get("id") for p in found])
    for p in found:
        p["verified"] = "linkedin" in verified.get(by_handle[p["handle"]].get("id"), [])


def _mark_sent(handle: str, day: str, snap: dict | None) -> None:
    payload = dict(snap or {})
    payload["digest_sent_on"] = day
    config.get_supabase().table("agent_profile_cards").update(
        {"suggested_posts": payload}
    ).eq("handle", handle).execute()


def clear_suggested_posts(*, handle: str | None = None) -> dict:
    want = (handle or "").strip().lstrip("@").lower()
    q = config.get_supabase().table("agent_profile_cards").update({"suggested_posts": None})
    if want:
        q = q.eq("handle", want)
    else:
        q = q.neq("id", "")  # PostgREST refuses unfiltered UPDATE
    rows = q.execute().data or []
    stats = {"cleared": len(rows)}
    if want and not rows:
        stats["not_found"] = True
    return stats


def run_digest(
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    handle: str | None = None,
    ignore_schedule: bool = False,
) -> dict:
    """Send the digest to every owner whose local clock is inside their 07:00 window.

    Meant to be called every 30 minutes. `digest_sent_on` holds the owner's local date, so
    repeated ticks send at most one digest per owner per local day. `handle` or
    `ignore_schedule` skips the window check (previews, manual sends); the sent-today check
    still applies. Owners who turned the morning digest off are skipped, except in dry runs.
    """
    now = now or datetime.now(timezone.utc)
    stats = {"sent": 0, "skipped_no_email": 0, "skipped_not_due": 0, "skipped_already": 0,
             "skipped_unsubscribed": 0, "errors": 0}
    want = (handle or "").strip().lstrip("@").lower()
    all_rows = _list_digest_rows()
    rows = all_rows
    if want:
        rows = [r for r in rows if (r.get("handle") or "").lower() == want]
        if not rows:
            stats["not_found"] = True
            return stats
    if dry_run:
        stats["previews"] = []
    for row in rows:
        handle = row.get("handle") or ""
        email = (row.get("owner_email") or "").strip()
        snap = row.get("suggested_posts") if isinstance(row.get("suggested_posts"), dict) else {}
        if not handle:
            continue
        if not email:
            stats["skipped_no_email"] += 1
            continue
        prefs = row.get("notification_prefs") if isinstance(row.get("notification_prefs"), dict) else {}
        if prefs.get("morning_digest") is False and not dry_run:
            stats["skipped_unsubscribed"] += 1
            continue
        local = now.astimezone(resolve_zone(row.get("timezone")))
        if not (want or ignore_schedule or _in_send_window(local)):
            stats["skipped_not_due"] += 1
            continue
        day = local.date().isoformat()
        if snap.get("digest_sent_on") == day:
            stats["skipped_already"] += 1
            continue
        try:
            posts = get_suggested_posts(handle)
            people = get_suggested_people(handle) or {"people": [], "outside": []}
            try:
                _mark_people(row, people, all_rows)
            except Exception as exc:  # noqa: BLE001 — badges are extras; send without them
                logger.info("digest people marks failed handle=%s err=%s", handle, exc)
            extras = _owner_extras(row, all_rows, now, local)
            name = _identity_name(row.get("card"))
            body = render_digest(handle, posts, people, name=name, extras=extras)
            html = render_digest_html(handle, posts, people, name=name, extras=extras)
            subject = digest_subject(build_digest(handle, posts, people, name, extras))
            if dry_run:
                stats["previews"].append({"handle": handle, "to": email, "subject": subject, "body": body, "html": html})
            else:
                merged = dict(snap)
                if isinstance(posts, dict):
                    merged.update({k: posts[k] for k in ("date", "posts", "summary", "shown_urls", "queries_hash") if k in posts})
                # Claim the day before sending. The next tick is 30 minutes away, so if the
                # marker were written after SMTP and that write failed, the owner would get
                # the same digest on every tick in the window. A failed send costs one day.
                _mark_sent(handle, day, merged)
                send_smtp(
                    to=email,
                    subject=subject,
                    body=body,
                    html=html,
                    unsubscribe_url=extras.get("unsubscribe_url"),
                )
            stats["sent"] += 1
        except Exception as exc:
            logger.warning("digest failed handle=%s err=%s", handle, exc)
            stats["errors"] += 1
    return stats
