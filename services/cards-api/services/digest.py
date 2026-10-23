"""Morning digest: email suggested posts + people to card owners via SMTP."""
from __future__ import annotations

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

# Gmail-safe palette from the digest mock (inline only — no Tailwind/CDN).
_BG = "#faf8ff"
_WHITE = "#ffffff"
_CARD = "#f2f3ff"
_INK = "#131b2e"
_MUTED = "#5a5a73"
_VARIANT = "#474553"
_PRIMARY = "#554ac0"
_SECONDARY = "#5044d5"
_LINE = "#c8c4d5"
_LI = "#0A66C2"
_FONT = "Arial,Helvetica,sans-serif"


def clip_summary(text: str, limit: int = 100) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit])


def digest_summary(text: str, limit: int = 100) -> str:
    parts = []
    for para in (text or "").split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if ": " in para:
            head, rest = para.split(": ", 1)
            if rest and len(head.split()) <= 6 and "." not in head:
                para = rest
        parts.append(para)
    return clip_summary(" ".join(parts), limit)


def _display_name(name: str | None, handle: str) -> str:
    n = (name or "").strip()
    return n or f"@{handle}"


def _identity_name(card) -> str:
    if not isinstance(card, dict):
        return ""
    ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    return (ident.get("name") or "").strip()


def render_digest(handle: str, posts: dict | None, people: dict | None, name: str | None = None) -> str:
    posts = posts or {}
    people = people or {}
    who = _display_name(name, handle)
    lines = [f"Morning digest for {who}", ""]
    summary = digest_summary((posts.get("summary") or "").strip())
    if summary:
        lines += ["SUMMARY", summary, ""]
    lines.append("POSTS")
    any_post = False
    for slot in posts.get("posts") or []:
        if not slot:
            continue
        any_post = True
        excerpt = clip_summary((slot.get("excerpt") or "").strip(), 30)
        url = slot.get("url") or ""
        lines.append(f"- {excerpt}")
        if url:
            lines.append(f"  {url}")
    if not any_post:
        lines.append("- none today")
    lines += ["", "PEOPLE ON ZYND"]
    zynd = people.get("people") or []
    if not zynd:
        lines.append("- none today")
    for p in zynd:
        name = p.get("name") or p.get("handle") or ""
        url = p.get("url") or ""
        lines.append(f"- {name}  {url}".rstrip())
    lines += ["", "OUTSIDE"]
    outside = people.get("outside") or []
    if not outside:
        lines.append("- none today")
    for p in outside:
        name = p.get("name") or ""
        title = p.get("title") or ""
        company = p.get("company") or ""
        url = p.get("linkedin_url") or ""
        who = ", ".join(x for x in (title, company) if x)
        lines.append(f"- {name}" + (f", {who}" if who else ""))
        if url:
            lines.append(f"  {url}")
    return "\n".join(lines).strip() + "\n"


def _esc(s: str) -> str:
    return html_lib.escape(s or "", quote=True)


def _card_url(handle: str) -> str:
    return f"{(config.SITE_BASE_URL or 'https://zynd.ai').rstrip('/')}/p/{handle}"


def _a(url: str, label: str, *, fill: bool = False, color: str | None = None) -> str:
    if not url:
        return ""
    if fill:
        return (
            f'<a href="{_esc(url)}" style="display:inline-block;padding:6px 10px;border-radius:6px;'
            f'background:{_PRIMARY};color:{_WHITE};text-decoration:none;font:400 11px/1 {_FONT}">'
            f"{_esc(label)}</a>"
        )
    c = color or _PRIMARY
    return (
        f'<a href="{_esc(url)}" style="display:inline-block;padding:6px 10px;border-radius:6px;'
        f'background:{_WHITE};color:{c};text-decoration:none;font:400 11px/1 {_FONT};'
        f'border:1px solid {_LINE}">{_esc(label)}</a>'
    )


def _initial(name: str) -> str:
    s = (name or "?").strip()
    return _esc(s[0].upper()) if s else "?"


def _heading(title: str, tag: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:12px 0 6px">'
        f'<tr><td style="font:400 13px/18px {_FONT};color:{_INK};padding-bottom:4px;'
        f'border-bottom:1px solid {_LINE}">{_esc(title)}</td>'
        f'<td align="right" style="font:400 10px/14px {_FONT};color:{_MUTED};padding-bottom:4px;'
        f'border-bottom:1px solid {_LINE};white-space:nowrap">{_esc(tag)}</td></tr></table>'
    )


def _empty() -> str:
    return f'<p style="margin:0;font:12px/18px {_FONT};color:{_MUTED}">none today</p>'


def _post_label(url: str) -> str:
    u = (url or "").lower()
    if "x.com" in u or "twitter.com" in u:
        return "View Post on X"
    if "linkedin.com" in u:
        return "View Post on LinkedIn"
    return "View Post"


def _post_card(slot: dict) -> str:
    excerpt = clip_summary((slot.get("excerpt") or "").strip(), 30)
    url = slot.get("url") or ""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{_CARD};border-radius:8px;margin:0 0 8px">'
        f'<tr><td style="padding:10px">'
        f'<p style="margin:0 0 8px;padding:0 0 0 8px;border-left:2px solid {_PRIMARY};'
        f'font:italic 12px/18px {_FONT};color:{_INK}">{_esc(excerpt)}</p>'
        f'<div style="text-align:right">{_a(url, _post_label(url))}</div>'
        f"</td></tr></table>"
    )


def _person_card(
    *,
    name: str,
    sub: str,
    url: str,
    cta: str,
    badge: str,
    fill: bool,
    avatar_bg: str,
    avatar_fg: str,
) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{_CARD};border-radius:8px;margin:0 0 8px">'
        f'<tr><td style="padding:10px 10px 4px" width="40" valign="top">'
        f'<div style="width:32px;height:32px;border-radius:16px;background:{avatar_bg};color:{avatar_fg};'
        f'font:400 14px/32px {_FONT};text-align:center">{_initial(name)}</div></td>'
        f'<td style="padding:10px 10px 4px" valign="middle">'
        f'<div style="font:400 13px/18px {_FONT};color:{_INK}">{_esc(name)} '
        f'<span style="color:{_MUTED};font:400 10px/14px {_FONT}">{_esc(badge)}</span></div>'
        f'<div style="font:400 12px/16px {_FONT};color:{_VARIANT}">{_esc(sub)}</div></td></tr>'
        f'<tr><td colspan="2" style="padding:0 10px 10px">{_a(url, cta, fill=fill)}</td>'
        f"</tr></table>"
    )


def render_digest_html(handle: str, posts: dict | None, people: dict | None, name: str | None = None) -> str:
    posts = posts or {}
    people = people or {}
    card = _card_url(handle)
    who = _display_name(name, handle)
    summary = digest_summary((posts.get("summary") or "").strip())

    post_cards = [_post_card(s) for s in (posts.get("posts") or []) if s]
    zynd_cards = []
    for p in people.get("people") or []:
        pname = p.get("name") or p.get("handle") or ""
        zynd_cards.append(_person_card(
            name=pname,
            sub=p.get("headline") or "",
            url=p.get("url") or "",
            cta="View Zynd Profile",
            badge="Native Network",
            fill=True,
            avatar_bg=_SECONDARY,
            avatar_fg=_WHITE,
        ))
    outside_cards = []
    for p in people.get("outside") or []:
        pname = p.get("name") or ""
        title, company = (p.get("title") or "").strip(), (p.get("company") or "").strip()
        sub = f"{title} at {company}" if title and company else (title or company)
        outside_cards.append(_person_card(
            name=pname,
            sub=sub,
            url=p.get("linkedin_url") or "",
            cta="Connect on LinkedIn",
            badge="LinkedIn Graph",
            fill=False,
            avatar_bg="#dae2fd",
            avatar_fg=_VARIANT,
        ))

    summary_block = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:#eaedff;border-radius:8px;margin:0 0 8px">'
        f'<tr><td style="padding:10px">'
        f'<div style="font:400 10px/14px {_FONT};color:{_MUTED};letter-spacing:.06em;text-transform:uppercase">'
        f"Executive Digest</div>"
        f'<div style="margin-top:4px;font:400 12px/18px {_FONT};color:{_INK}">{_esc(summary)}</div>'
        f"</td></tr></table>"
        if summary else ""
    )

    def section(title: str, tag: str, cards: list[str]) -> str:
        return _heading(title, tag) + ("".join(cards) if cards else _empty())

    return (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;background:{_BG}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG}">'
        f'<tr><td align="center" style="padding:8px">'
        f'<table role="presentation" width="620" cellpadding="0" cellspacing="0" '
        f'style="max-width:620px;width:100%;background:{_WHITE};border-radius:8px">'
        f'<tr><td style="height:6px;line-height:6px;font-size:0;background:{_PRIMARY}">&nbsp;</td></tr>'
        f'<tr><td style="padding:12px 14px 16px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="32" valign="middle"><div style="width:28px;height:28px;border-radius:6px;'
        f'background:{_PRIMARY};color:{_WHITE};font:400 16px/28px {_FONT};text-align:center">Z</div></td>'
        f'<td valign="middle" style="padding-left:8px">'
        f'<div style="font:400 16px/20px {_FONT};color:{_INK}">Zynd</div>'
        f'<div style="font:400 11px/14px {_FONT};color:{_MUTED}">Morning digest</div></td>'
        f"</tr></table>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{_CARD};border-radius:8px;margin:12px 0 8px">'
        f'<tr><td style="padding:10px">'
        f'<div style="font:400 14px/20px {_FONT};color:{_INK}">Good morning, {_esc(who)}!</div>'
        f'<p style="margin:4px 0 0;font:12px/18px {_FONT};color:{_VARIANT}">'
        f"Today's suggested posts and people for your card.</p>"
        f"</td></tr></table>"
        f"{summary_block}"
        f"{section('Curated Posts & Signals', f'{len(post_cards)} matched', post_cards)}"
        f"{section('People on Zynd', 'Native Network', zynd_cards)}"
        f"{section('Outside Network Opportunities', 'LinkedIn Graph', outside_cards)}"
        f'<p style="margin:16px 0 0;padding-top:10px;border-top:1px solid {_LINE};'
        f'font:11px/16px {_FONT};color:{_MUTED}">'
        f'<a href="{_esc(card)}" style="color:{_PRIMARY};text-decoration:underline">Public Card ({_esc(card.replace("https://", ""))})</a>'
        f" · Sent by Zynd</p>"
        f"</td></tr></table></td></tr></table></body></html>"
    )


def send_smtp(*, to: str, subject: str, body: str, html: str | None = None) -> None:
    if not config.SMTP_HOST or not config.SMTP_USER:
        raise RuntimeError("SMTP_HOST / SMTP_USER not set")
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
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


def _list_digest_rows() -> list[dict]:
    columns = "handle,owner_email,suggested_posts,card"
    try:
        return cards_service.list_published_rows(columns=columns + ",timezone")
    except APIError as exc:
        # 42703 = undefined column: cards-api is deployed ahead of migration 0029 (or still on
        # the pre-cards schema). Everyone gets the default zone, as before, instead of no digest.
        if str(exc.code) != "42703":
            raise
        logger.warning("digest: timezone column missing, using %s for everyone", config.DIGEST_DEFAULT_TIMEZONE)
        return cards_service.list_published_rows(columns=columns)


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
    still applies.
    """
    now = now or datetime.now(timezone.utc)
    stats = {"sent": 0, "skipped_no_email": 0, "skipped_not_due": 0, "skipped_already": 0, "errors": 0}
    want = (handle or "").strip().lstrip("@").lower()
    rows = _list_digest_rows()
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
            name = _identity_name(row.get("card"))
            body = render_digest(handle, posts, people, name=name)
            html = render_digest_html(handle, posts, people, name=name)
            if dry_run:
                stats["previews"].append({"handle": handle, "to": email, "body": body, "html": html})
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
                    subject=f"Your Zynd morning digest @{handle}",
                    body=body,
                    html=html,
                )
            stats["sent"] += 1
        except Exception as exc:
            logger.warning("digest failed handle=%s err=%s", handle, exc)
            stats["errors"] += 1
    return stats
