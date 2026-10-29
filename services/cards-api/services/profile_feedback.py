"""One feedback invitation per normalized owner email, using the existing delivery ledger."""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

import config
from services import owner_home, owner_notifications

FEEDBACK_AFTER_DAYS = 3
FEEDBACK_KIND = "profile_feedback"
FEEDBACK_PERIOD = "once"
SUBJECT = "How’s your Zynd profile experience so far?"
CALENDAR_URL = "https://calendar.app.google/w2Z4zamwn58ZH3856"
FORM_URL = "https://forms.gle/HnTCsrEofid3wBf99"


def render_feedback(name: str, unsubscribe_url: str | None, *, handle: str | None = None,
                    preview_label: str | None = None) -> tuple[str, str]:
    first_name = (name or "").strip().split()[0] if (name or "").strip() else "there"
    paragraphs = [
        f"Hey {first_name},",
        "You created your Zynd profile a few days ago, and we'd love to hear how your experience has been so far!",
        "We're still improving Zynd, and talking to people using it helps us understand what's working, what's missing, and what we should build next.",
        "Would you be open to a quick 15-minute call with us? We'd love to see how you're using your profile, hear your thoughts, and learn what would make it more useful for you.",
        "📅 Book a quick chat: " + CALENDAR_URL,
        "Can't make a call? No worries! You can share your thoughts in this quick form instead:\n" + FORM_URL,
        "Thanks for being an early part of Zynd. Your feedback can genuinely help shape what we build next.",
        "Best,\nTeam Zynd",
    ]
    body = "\n\n".join(paragraphs)
    if unsubscribe_url:
        body += "\n\nUnsubscribe: " + unsubscribe_url
    from services.feedback_email import render_feedback_html
    markup = render_feedback_html(name, paragraphs, CALENDAR_URL, FORM_URL, unsubscribe_url,
                                  handle=handle, preview_label=preview_label)
    return body, markup


def email_allowed(row: dict | None) -> bool:
    if not row or row.get("status") != "published":
        return False
    prefs = {**owner_home.DEFAULT_PREFS, **(row.get("notification_prefs") or {})}
    # Respect an owner who has opted out of owner emails. This endpoint never
    # changes preferences or bypasses an unsubscribe.
    return bool(prefs["weekly_digest"] or prefs["email_nudges"])


async def run_feedback(*, email: str | None = None, dry_run: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if email is not None:
        email = email.strip().lower()
        if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email):
            raise HTTPException(422, "email must be a single card-owner email address")
    if not owner_home.enabled():
        raise HTTPException(404, "Owner home is not enabled")
    adapter = None if dry_run else owner_notifications._test_mailer()
    rows = await asyncio.to_thread(owner_notifications.notification_rows)
    groups = {}
    for row in rows:
        address = (row.get("owner_email") or "").strip().lower()
        if address and (email is None or address == email):
            groups.setdefault(address, []).append(row)
    stats = {"sent": 0, "skipped": 0, "failed": 0, "previews": []}
    for address, owned in groups.items():
        try:
            row = next((r for r in owned if r.get("status") == "published"), None)
            created = [datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                       for r in owned if isinstance(r.get("created_at"), str)]
            if (not email_allowed(row) or not created or any(t.tzinfo is None for t in created)
                    or min(created) > now - timedelta(days=FEEDBACK_AFTER_DAYS)
                    or not row.get("unsubscribe_token")):
                stats["skipped"] += 1
                continue
            unsubscribe = config.API_BASE_URL.rstrip("/") + "/cards/notifications/unsubscribe/" + str(row["unsubscribe_token"])
            name = ((row.get("card") or {}).get("identity") or {}).get("name") or ""
            body, markup = render_feedback(name, unsubscribe, handle=row.get("handle"))
            if dry_run:
                stats["previews"].append({"to": address, "subject": SUBJECT, "body": body, "html": markup})
                continue
            delivery = await asyncio.to_thread(owner_notifications.claim_delivery, address, FEEDBACK_KIND, FEEDBACK_PERIOD)
            if delivery is None:
                stats["skipped"] += 1
                continue
            state = "failed"
            try:
                latest = await asyncio.to_thread(owner_home.current_row, address)
                if not email_allowed(latest):
                    state = "cancelled"
                    stats["skipped"] += 1
                else:
                    await asyncio.to_thread(adapter.send, to=address, subject=SUBJECT, body=body, html=markup, unsubscribe_url=unsubscribe)
                    state = "sent"
                    stats["sent"] += 1
            except Exception:
                stats["failed"] += 1
            await asyncio.to_thread(lambda: config.get_supabase().table("notification_deliveries").update(
                {"status": state, "sent_at": now.isoformat() if state == "sent" else None}).eq("id", delivery).execute())
        except Exception:
            stats["failed"] += 1
    return stats
