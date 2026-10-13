"""S10 weekly owner digest and rate-limited nudge delivery."""
from __future__ import annotations

import asyncio
import html
from datetime import datetime, timezone
from urllib.parse import quote

from postgrest.exceptions import APIError

import config
from services import owner_home
from services.mailer import get_mailer


def week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def render_weekly(data: dict, unsubscribe_url: str | None) -> tuple[str, str]:
    base = config.SITE_BASE_URL.rstrip("/")
    inbox = base + "/p/" + quote(data["handle"], safe="") + "/edit#inbox"
    metrics = data["activity"]
    counts = (f"{metrics['views']} human views · {metrics['agent_hits']} agent hits in the last 7 days"
              if metrics["available"] else "Activity measurement is unavailable this week.")
    pending = data["inbox_count"]
    waiting = f"{pending} facts waiting for review" if pending is not None else "Review queue is temporarily unavailable"
    questions = [str(q.get("query", ""))[:160] for q in metrics.get("queries", []) if q.get("query")]
    lines = [f"Your week on Zynd, {data['name'] or data['handle']}", counts, waiting,
             f"Card completeness: {data['completeness']['score']}%", "", "Questions that found your card:",
             *(questions or ["Matching queries are not recorded yet."]), "", f"Review your inbox: {inbox}",
             f"Owner home: {base}/home"]
    body = "\n".join(lines)
    intro_waiting = data.get("intro_inbox_count")
    if intro_waiting is not None:
        body += f"\n{intro_waiting} intro requests waiting for your decision\nReview introductions: {base}/intros"
    if unsubscribe_url:
        body += "\n\nUnsubscribe: " + unsubscribe_url
    esc = lambda value: html.escape(str(value), quote=True)
    content = "".join(f"<p>{esc(line)}</p>" for line in lines[:4])
    markup = (f'<!doctype html><html><body style="background:#faf8ff;color:#131b2e;font:16px/1.6 Arial,sans-serif;padding:24px">'
              f'<main style="max-width:600px;margin:auto;background:white;padding:24px;border-radius:16px"><h1>Your week on Zynd</h1>{content}'
              '<h2>Questions that found your card</h2><ul>' + "".join(f"<li>{esc(q)}</li>" for q in (questions or ["Matching queries are not recorded yet."])) + '</ul>'
              f'<p><a href="{esc(inbox)}">Review your inbox</a> · <a href="{esc(base + "/home")}">Owner home</a></p>'
              + (f'<p>{intro_waiting} intro requests waiting. <a href="{esc(base + "/intros")}">Review introductions</a></p>' if intro_waiting is not None else '')
              + (f'<footer>You receive this because you own a Zynd card. <a href="{esc(unsubscribe_url)}">Unsubscribe</a></footer>' if unsubscribe_url else '<footer>Preview only</footer>')
              + '</main></body></html>')
    return body, markup


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


async def run_notifications(*, dry_run: bool = False, now: datetime | None = None) -> dict:
    stats = {"sent": 0, "skipped": 0, "failed": 0, "previews": []}
    if not owner_home.enabled():
        return stats
    now = now or datetime.now(timezone.utc)
    adapter = get_mailer()
    # One canonical row per normalized owner, including private cards for
    # in-app nudges. Emails are only sent for published cards.
    def all_rows():
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
    rows = await asyncio.to_thread(all_rows)
    by_owner = {}
    for row in rows:
        email = (row.get("owner_email") or "").strip().lower()
        if email and (email not in by_owner or (by_owner[email]["status"] != "published" and row["status"] == "published")):
            by_owner[email] = row
    for email, row in by_owner.items():
        try:
            data = await owner_home.status(email, persist=not dry_run)
            if not data:
                continue
            if dry_run:
                stats["previews"].append({"handle": data["handle"], "body": render_weekly(data, None)[0]})
                continue
            if not config.FEATURE_S10_DIGEST or not adapter.enabled or row["status"] != "published":
                stats["skipped"] += 1
                continue
            prefs = data["notification_prefs"]
            unsubscribe = config.API_BASE_URL.rstrip("/") + "/cards/notifications/unsubscribe/" + str(row["unsubscribe_token"])
            messages = []
            if prefs["weekly_digest"]:
                body, markup = render_weekly(data, unsubscribe)
                messages.append(("weekly", week_key(now), "Your week on Zynd", body, markup))
            if prefs["email_nudges"] and data["nudges"]:
                # Only send newly created nudges, once daily. Older reminders
                # remain in-app without generating another email each day.
                fresh = [n for n in data["nudges"] if str(n.get("created_at", ""))[:10] == now.date().isoformat()]
                if fresh:
                    text = "\n".join(n["title"] for n in fresh) + "\n" + config.SITE_BASE_URL.rstrip("/") + "/home\nUnsubscribe: " + unsubscribe
                    markup = '<!doctype html><p>' + html.escape(text).replace('\n', '<br>') + '</p><a href="' + html.escape(config.SITE_BASE_URL.rstrip('/') + '/home', quote=True) + '">Open owner home</a><p><a href="' + html.escape(unsubscribe, quote=True) + '">Unsubscribe</a></p>'
                    messages.append(("nudge", now.date().isoformat(), "Your Zynd card needs attention", text, markup))
            for kind, period, subject, body, markup in messages:
                delivery = await asyncio.to_thread(claim_delivery, email, kind, period)
                if delivery is None:
                    stats["skipped"] += 1
                    continue
                try:
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
