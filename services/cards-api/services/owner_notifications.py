"""S10 weekly owner digest and rate-limited nudge delivery."""
from __future__ import annotations

import asyncio
import html
import re
import smtplib
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError
from fastapi import HTTPException

import config
from services import owner_home
from services.mailer import get_mailer
from services.weekly_email import DASHBOARD_URL, render_weekly_html, visitor_profile_url

WEEKLY_VISITOR_LIMIT = 10


def _weekly_visitor_details(data: dict) -> tuple[list[str], list[str]]:
    """Use saved client labels and the consent-filtered visitor view only."""
    clients = data["activity"].get("agent_clients")
    agents = [f"{a['provider']} — {a['name']}: {a['count']} {'request' if a['count'] == 1 else 'requests'}"
              for a in (clients or [])]
    if not agents:
        agents = ["Agent client identities are unavailable." if clients is None
                  else "No AI client requests recorded this week."]
    visitors = data.get("visitors") or {}
    people = []
    if visitors.get("available"):
        for visitor in (visitors.get("items") or [])[:WEEKLY_VISITOR_LIMIT]:
            name = (visitor.get("name") or "").strip()
            if not name:
                continue
            visits = visitor.get("visits")
            suffix = f" ({visits} {'visit' if visits == 1 else 'visits'})" if isinstance(visits, int) and visits > 0 else ""
            profile = visitor_profile_url(visitor)
            people.append(name + suffix + (" — " + profile if profile else ""))
    if not people:
        people = ["No visitors chose to share their name this week." if visitors.get("available")
                  else "Visitor names are unavailable."]
    return agents, people


def week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def render_weekly(data: dict, unsubscribe_url: str | None, *, preview_label: str = "Preview only") -> tuple[str, str]:
    base = config.SITE_BASE_URL.rstrip("/")
    inbox = config.profile_url(data["handle"]) + "/edit#inbox"
    metrics = data["activity"]
    from services.read_receipt_topics import question_insights
    insights = question_insights(metrics, data.get("name") or "")
    counts = (f"{metrics['views']} human views · {metrics['agent_hits']} agent hits in the last 7 days"
              if metrics["available"] else "Activity measurement is unavailable this week.")
    pending = data["inbox_count"]
    waiting = f"{pending} facts waiting for review" if pending is not None else "Review queue is temporarily unavailable"
    questions = insights["questions"]
    agents, visitors = _weekly_visitor_details(data)
    matches = (data.get("suggestions") or {}).get("people") or []
    lines = [f"Your week on Zynd, {data['name'] or data['handle']}"]
    if matches:
        lines += ["", "Zynd matches — review before sending an intro"]
        for person in matches[:3]:
            lines.append(f"- {person.get('name') or person.get('handle')}: " + "; ".join(person.get("why") or []))
        lines.append(f"Review matches and draft an intro: {DASHBOARD_URL}#zynd-matches")
    lines += ["", counts, waiting,
             f"Card completeness: {data['completeness']['score']}%", "",
             "People who visited (last 7 days):", *visitors,
             "Names appear only for visitors who chose to share them; anonymous visits remain anonymous.", "",
             "AI clients that accessed your profile (last 7 days):", *agents,
             "Reported client identities, not verified model names. Breakdown covers the latest 1,000 AI requests.", "",
             *( ["Topics asked about in your profile assistant: " + ", ".join(insights["topics"])] if insights["topics"] else []),
             "Recent profile-assistant questions (last 7 days):",
             *(questions or ["No profile-assistant questions recorded this week."]),
             "AI requests and assistant questions are separate measurements; crawler requests may not include a question.", "", f"Review your inbox: {inbox}",
             f"Owner home: {DASHBOARD_URL}"]
    from services import digest_network
    lines += digest_network.lines(data.get("network"))
    body = "\n".join(lines)
    intro_waiting = data.get("intro_inbox_count")
    if intro_waiting is not None:
        body += f"\n{intro_waiting} intro requests waiting for your decision\nReview introductions: {base}/intros"
    if unsubscribe_url:
        body += "\n\nUnsubscribe: " + unsubscribe_url
    esc = lambda value: html.escape(str(value), quote=True)
    markup = render_weekly_html(data, insights, agents, visitors, unsubscribe_url, preview_label,
                                _network_html(data.get("network"), esc))
    return body, markup


def _network_html(network: dict | None, esc) -> str:
    from services import digest_network
    rows = digest_network.lines(network)[2:]
    if not rows:
        return ""
    return "<h2>Your network this week</h2><ul>" + "".join(f"<li>{esc(r.removeprefix('- '))}</li>" for r in rows) + "</ul>"


def render_reminder(nudges: list[dict], unsubscribe_url: str | None) -> tuple[str, str]:
    home = config.SITE_BASE_URL.rstrip("/") + "/home"
    text = "\n".join(n["title"] for n in nudges) + "\n" + home
    if unsubscribe_url:
        text += "\nUnsubscribe: " + unsubscribe_url
    markup = ('<!doctype html><p>' + html.escape(text).replace('\n', '<br>')
              + '</p><a href="' + html.escape(home, quote=True) + '">Open owner home</a>')
    if unsubscribe_url:
        markup += '<p><a href="' + html.escape(unsubscribe_url, quote=True) + '">Unsubscribe</a></p>'
    return text, markup


def _test_mailer():
    if not owner_home.enabled():
        raise HTTPException(404, "Owner home is not enabled")
    adapter = get_mailer()
    if not adapter.enabled:
        raise HTTPException(503, "Set S10_MAILER=smtp and restart Cards API")
    if not config.SMTP_HOST or not config.SMTP_FROM:
        raise HTTPException(503, "Configure SMTP_HOST and SMTP_FROM and restart Cards API")
    return adapter


async def send_test_notification(*, email: str, kind: str = "weekly") -> dict:
    """One explicit send. Never changes consent or claims a scheduled delivery."""
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email):
        raise HTTPException(422, "email must be a single card-owner email address")
    if kind not in {"weekly", "reminder", "feedback"}:
        raise HTTPException(422, "Choose weekly, reminder or feedback")
    adapter = _test_mailer()
    try:
        data = await owner_home.status(email, persist=False)
    except Exception as exc:
        raise HTTPException(503, "Could not load the test owner's card data") from exc
    if data is None:
        raise HTTPException(404, "email must match an existing card owner")
    notice = "Test email requested manually; email preferences and delivery limits were bypassed."
    if kind == "weekly":
        body, markup = await asyncio.to_thread(render_weekly, data, None, preview_label=notice)
        subject = "[TEST] Your week on Zynd"
    elif kind == "feedback":
        from services.profile_feedback import render_feedback, SUBJECT
        body, markup = render_feedback(data.get("name") or "", None,
                                       handle=data.get("handle"), preview_label=notice)
        subject = "[TEST] " + SUBJECT
    else:
        nudges = data.get("nudges") or [{"title": "Sample reminder: there are no current reminders for this card."}]
        body, markup = render_reminder(nudges, None)
        markup += "<footer>" + html.escape(notice) + "</footer>"
        subject = "[TEST] Your Zynd card needs attention"
    try:
        await asyncio.to_thread(adapter.send, to=email, subject=subject, body=notice + "\n\n" + body,
                                html=markup, unsubscribe_url=None)
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(502, "SMTP authentication failed; check SMTP_USER and SMTP_PASSWORD") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise HTTPException(502, "SMTP rejected the test recipient; check sandbox recipient restrictions") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise HTTPException(502, "SMTP rejected the sender; check SMTP_FROM and sender verification") from exc
    except Exception as exc:
        raise HTTPException(502, "SMTP test send failed; check host, port, STARTTLS support, and provider settings") from exc
    return {"sent": 1, "to": email, "kind": kind, "test": True}


def _test_owner_emails() -> list[str]:
    sb = config.get_supabase()
    emails, offset = set(), 0
    while True:
        rows = (sb.table("agent_profile_cards").select("owner_email")
                .neq("status", "merged").not_.is_("owner_email", "null")
                .order("id").range(offset, offset + 499).execute().data or [])
        emails.update(row["owner_email"].strip().lower() for row in rows if (row.get("owner_email") or "").strip())
        if len(rows) < 500:
            return sorted(emails)
        offset += 500


async def send_all_test_notifications(*, kind: str = "weekly") -> dict:
    """Force a test send once per normalized card owner, continuing on per-owner errors."""
    _test_mailer()
    try:
        emails = await asyncio.to_thread(_test_owner_emails)
    except Exception as exc:
        raise HTTPException(503, "Could not load card-owner email addresses") from exc
    result = {"sent": 0, "failed": 0, "kind": kind, "test": True, "errors": []}
    for email in emails:
        try:
            await send_test_notification(email=email, kind=kind)
            result["sent"] += 1
        except HTTPException as exc:
            result["failed"] += 1
            result["errors"].append({"email": email, "status": exc.status_code, "detail": exc.detail})
        except Exception:
            result["failed"] += 1
            result["errors"].append({"email": email, "status": 503, "detail": "Could not prepare the test notification"})
    return result


def claim_delivery(email: str, kind: str, period: str) -> str | None:
    try:
        rows = config.get_supabase().table("notification_deliveries").insert({
            "owner_email": email, "kind": kind, "period": period,
        }).execute().data or []
        return rows[0]["id"] if rows else None
    except APIError as exc:
        if str(exc.code) == "23505":
            return None
        raise


def _network_section(email: str, row: dict, all_rows: list[dict]) -> dict | None:
    """A4: mutual matches, what connections changed, saved-search hits. Best effort and
    off unless network controls are on: the digest must never fail because of it."""
    from services import digest_network, network, trust
    if not trust.enabled() or not row.get("owner_user_id"):
        return None
    try:
        me = digest_network._card(row)
        user_id = row["owner_user_id"]
        conns = network._sb().table("connections").select("*").or_(
            f"requester_user_id.eq.{user_id},recipient_user_id.eq.{user_id}").execute().data or []
        partner_ids = [c["recipient_card_id"] if c["requester_user_id"] == user_id else c["requester_card_id"]
                       for c in conns if c.get("status") == "accepted"]
        by_id = {r["id"]: r for r in all_rows if r.get("id")}
        partners = [c for c in (digest_network._card(by_id[i]) for i in partner_ids if i in by_id) if c]
        linked = {r["handle"] for r in all_rows if r.get("id") in {c["recipient_card_id"] for c in conns} | {c["requester_card_id"] for c in conns}}
        hits = network._sb().table("card_nudges").select("title").eq("owner_email", email).eq("kind", "saved_search") \
            .gte("created_at", (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()).execute().data or []
        return digest_network.section(
            digest_network.mutual_matches(me, [r for r in all_rows if r.get("status") == "published"], linked) if me else [],
            digest_network.connection_updates(partners), [h["title"] for h in hits])
    except Exception:  # noqa: BLE001
        return None


def notification_rows() -> list[dict]:
    """Page through owners in the same canonical order used by owner home."""
    sb = config.get_supabase()
    rows, offset = [], 0
    while True:
        page = (sb.table("agent_profile_cards").select("*").neq("status", "merged")
                .not_.is_("owner_email", "null").order("created_at", desc=True).order("id")
                .range(offset, offset + 499).execute().data or [])
        rows.extend(page)
        if len(page) < 500:
            return rows
        offset += 500


async def run_notifications(*, dry_run: bool = False, now: datetime | None = None,
                            weekly_only: bool = False, email: str | None = None) -> dict:
    recipient = email.strip().lower() if email is not None else None
    if recipient is not None and not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", recipient):
        raise HTTPException(422, "email must be a single card-owner email address")
    stats = {"sent": 0, "skipped": 0, "failed": 0, "previews": []}
    if not owner_home.enabled():
        return stats
    now = now or datetime.now(timezone.utc)
    adapter = get_mailer()
    # One canonical row per normalized owner, including private cards for
    # in-app nudges. Emails are only sent for published cards.
    rows = await asyncio.to_thread(notification_rows)
    by_owner = {}
    for row in rows:
        email = (row.get("owner_email") or "").strip().lower()
        if recipient is not None and email != recipient:
            continue
        if email and (email not in by_owner or (by_owner[email]["status"] != "published" and row["status"] == "published")):
            by_owner[email] = row
    if recipient is not None and not by_owner:
        raise HTTPException(404, "email must match an existing card owner")
    for email, row in by_owner.items():
        try:
            data = await owner_home.status(email, persist=not dry_run)
            if not data:
                continue
            data["network"] = await asyncio.to_thread(_network_section, email, row, rows)
            if dry_run:
                body, _ = await asyncio.to_thread(render_weekly, data, None)
                stats["previews"].append({"handle": data["handle"], "body": body})
                continue
            if not adapter.enabled or row["status"] != "published":
                stats["skipped"] += 1
                continue
            prefs = data["notification_prefs"]
            unsubscribe = config.API_BASE_URL.rstrip("/") + "/cards/notifications/unsubscribe/" + str(row["unsubscribe_token"])
            messages = []
            if prefs["weekly_digest"]:
                # Claim first: repeated scheduler ticks must not regenerate an
                # LLM topic summary for an email already sent this week.
                messages.append(("weekly", week_key(now), "Your week on Zynd", None, None))
            if not weekly_only and config.FEATURE_S10_DIGEST and prefs["email_nudges"] and data["nudges"]:
                # Only send newly created nudges, once daily. Older reminders
                # remain in-app without generating another email each day.
                fresh = [n for n in data["nudges"] if str(n.get("created_at", ""))[:10] == now.date().isoformat()]
                if fresh:
                    text, markup = render_reminder(fresh, unsubscribe)
                    messages.append(("nudge", now.date().isoformat(), "Your Zynd card needs attention", text, markup))
            for kind, period, subject, body, markup in messages:
                delivery = await asyncio.to_thread(claim_delivery, email, kind, period)
                if delivery is None:
                    stats["skipped"] += 1
                    continue
                try:
                    if kind == "weekly":
                        body, markup = await asyncio.to_thread(render_weekly, data, unsubscribe)
                    # Re-read consent after claiming, immediately before send.
                    latest = await asyncio.to_thread(owner_home.current_row, email)
                    latest_prefs = {**owner_home.DEFAULT_PREFS, **(latest or {}).get("notification_prefs", {})}
                    if not latest or latest["status"] != "published" or not latest_prefs["weekly_digest" if kind == "weekly" else "email_nudges"]:
                        state = "cancelled"
                        stats["skipped"] += 1
                    else:
                        await asyncio.to_thread(adapter.send, to=email, subject=subject, body=body, html=markup, unsubscribe_url=unsubscribe)
                        state = "sent"
                        stats["sent"] += 1
                except Exception:
                    state = "failed"
                    stats["failed"] += 1
                def mark():
                    return config.get_supabase().table("notification_deliveries").update({"status": state, "sent_at": now.isoformat() if state == "sent" else None}).eq("id", delivery).execute()
                await asyncio.to_thread(mark)
        except Exception:
            stats["failed"] += 1
    return stats
