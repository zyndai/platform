"""Morning digest: email suggested posts + people to card owners via SMTP."""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import config
from services import cards as cards_service
from services.suggested_people import get_suggested_people
from services.suggested_posts import get_suggested_posts

logger = logging.getLogger(__name__)


def render_digest(handle: str, posts: dict | None, people: dict | None) -> str:
    posts = posts or {}
    people = people or {}
    lines = [f"Morning digest for @{handle}", ""]
    summary = (posts.get("summary") or "").strip()
    if summary:
        lines += ["SUMMARY", summary, ""]
    lines.append("POSTS")
    any_post = False
    for slot in posts.get("posts") or []:
        if not slot:
            continue
        any_post = True
        field = slot.get("field") or ""
        excerpt = (slot.get("excerpt") or "").strip()
        url = slot.get("url") or ""
        lines.append(f"- {field}: {excerpt}")
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


def send_smtp(*, to: str, subject: str, body: str) -> None:
    if not config.SMTP_HOST or not config.SMTP_USER:
        raise RuntimeError("SMTP_HOST / SMTP_USER not set")
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()
        if config.SMTP_PASSWORD:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)


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


def run_digest(*, today: str | None = None, dry_run: bool = False, handle: str | None = None) -> dict:
    day = today or datetime.now(timezone.utc).date().isoformat()
    stats = {"sent": 0, "skipped_no_email": 0, "skipped_already": 0, "errors": 0}
    want = (handle or "").strip().lstrip("@").lower()
    rows = cards_service.list_published_rows(columns="handle,owner_email,suggested_posts")
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
        if snap.get("digest_sent_on") == day:
            stats["skipped_already"] += 1
            continue
        try:
            posts = get_suggested_posts(handle)
            people = get_suggested_people(handle) or {"people": [], "outside": []}
            body = render_digest(handle, posts, people)
            if dry_run:
                stats["previews"].append({"handle": handle, "to": email, "body": body})
            else:
                send_smtp(
                    to=email,
                    subject=f"Your Zynd morning digest @{handle}",
                    body=body,
                )
                merged = dict(snap)
                if isinstance(posts, dict):
                    merged.update({k: posts[k] for k in ("date", "posts", "summary", "shown_urls", "queries_hash") if k in posts})
                _mark_sent(handle, day, merged)
            stats["sent"] += 1
        except Exception as exc:
            logger.warning("digest failed handle=%s err=%s", handle, exc)
            stats["errors"] += 1
    return stats
