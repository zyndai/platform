"""Builder wrap-ups. Facts are dated; drafts are private; public reads expose selected facts only."""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

import config
from scraping.github import fetch_period_contributions, github_handle_from_url
from scraping.github_recaps import fetch_period_activity
from services import owner_home
from services.companion import clean_url
from services.recap_captions import generate_social_caption

logger = logging.getLogger(__name__)
MAX_HIGHLIGHTS = 100
PAGE_SIZE = 100


def zone_for(row: dict) -> ZoneInfo:
    try:
        return ZoneInfo(row.get("timezone") or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def period_bounds(period: str, zone: ZoneInfo, now: datetime | None = None):
    """Calendar month/quarter, with an exclusive end. In-progress recaps are labelled in the UI."""
    if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])", period):
        raise HTTPException(422, "Choose a month (2026-10) or quarter (2026-Q3)")
    year = int(period[:4])
    month = (int(period[-1]) - 1) * 3 + 1 if "Q" in period else int(period[-2:])
    if not 2020 <= year <= 9998:
        raise HTTPException(422, "Choose a period from 2020 onwards")
    span = 3 if "Q" in period else 1
    start = datetime(year, month, 1, tzinfo=zone)
    end_month = month + span
    end = datetime(year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1, tzinfo=zone)
    now = now or datetime.now(timezone.utc)
    if start > now:
        raise HTTPException(422, "This period has not started yet")
    label = f"Q{period[-1]} {year}" if "Q" in period else f"{calendar.month_name[month]} {year}"
    return start, end, label


def previous_periods(now: datetime, zone: ZoneInfo) -> list[str]:
    local = now.astimezone(zone)
    last_month = local.date().replace(day=1) - timedelta(days=1)
    this_quarter = datetime(local.year, ((local.month - 1) // 3) * 3 + 1, 1, tzinfo=zone)
    last_quarter = this_quarter - timedelta(days=1)
    return [last_month.strftime("%Y-%m"), f"{last_quarter.year}-Q{(last_quarter.month - 1) // 3 + 1}"]


def current_card(email: str) -> dict:
    row = owner_home.current_row(email)
    if not row:
        raise HTTPException(404, "Create your card first")
    return row


def safe_url(raw: str) -> str:
    if not raw:
        return ""
    try:
        return clean_url(raw)
    except ValueError:
        return ""


def add_milestone(email: str, kind: str, title: str, url: str, occurred_on: date) -> dict:
    row = current_card(email)
    title = " ".join(title.split())
    if not title:
        raise HTTPException(422, "Give the milestone a title")
    if occurred_on > datetime.now(zone_for(row)).date():
        raise HTTPException(422, "A milestone cannot be in the future")
    if occurred_on.year < 2020:
        raise HTTPException(422, "Choose a date from 2020 onwards")
    normalized = safe_url(url)
    if url and not normalized:
        raise HTTPException(422, "Use a public http(s) evidence link")
    item = {"card_id": row["id"], "owner_email": email, "kind": kind, "title": title,
            "url": normalized, "occurred_on": occurred_on.isoformat()}
    sb = config.get_supabase()
    sb.table("card_milestones").upsert(item, on_conflict="card_id,owner_email,kind,title,occurred_on",
                                      ignore_duplicates=True).execute()
    return item


def _highlights(row: dict, milestones: list[dict], start: datetime, end: datetime) -> list[dict]:
    items, seen = [], set()
    for item in milestones:
        day = item["occurred_on"]
        if not start.date().isoformat() <= day < end.date().isoformat():
            continue
        # Repeated recording of the same shipped project within a period counts once.
        key = (item["kind"], safe_url(item.get("url", "")) or item["title"].casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append({"id": str(item["id"]), "kind": item["kind"], "title": item["title"],
                      "url": safe_url(item.get("url", "")), "date": day, "source": "owner_confirmed"})
    return sorted(items, key=lambda i: (i["date"], i["id"]), reverse=True)[:MAX_HIGHLIGHTS]


def _existing(row: dict, email: str, period: str) -> dict | None:
    rows = (config.get_supabase().table("card_recaps").select("*").eq("card_id", row["id"])
            .eq("owner_email", email).eq("period", period).limit(1).execute().data or [])
    return rows[0] if rows else None


def visible_snapshot(recap: dict) -> dict:
    selected = set(recap.get("selected_ids") or [])
    snap = recap["snapshot"]
    # Draft metadata may contain copy about subsequently hidden highlights. Owner-only.
    return {**{k: v for k, v in snap.items() if k != "_caption_draft"},
            "highlights": [h for h in snap["highlights"] if h["id"] in selected]}


def default_caption(snapshot: dict) -> str:
    highlights = snapshot["highlights"]
    def named(items):
        names = [h["title"] for h in items[:2]]
        text = " and ".join(names)
        return text + (f" and {len(items) - 2} more" if len(items) > 2 else "")
    parts = []
    repos = [h for h in highlights if h["kind"] == "repository"]
    shipped = [h for h in highlights if h["kind"] == "shipped"]
    learned = [h for h in highlights if h["kind"] == "learned"]
    contributions = next((h for h in highlights if h["kind"] == "github"), None)
    if repos:
        parts.append(f"created {len(repos)} new public {'repository' if len(repos) == 1 else 'repositories'} ({named(repos)})")
    if contributions:
        parts.append(f"made {contributions['count']} GitHub contributions")
    if shipped:
        parts.append(f"shipped {named(shipped)}")
    if learned:
        parts.append(f"learned {named(learned)}")
    period = snapshot["label"] + (" so far" if snapshot["in_progress"] else "")
    if not parts:
        return f"My {period} on Zynd: no highlights recorded yet."
    actions = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Hi connections, in {period}, I {actions}. Looking forward to sharing what comes next."[:2000]


async def generate(email: str, period: str, refresh: bool = False, row: dict | None = None,
                   now: datetime | None = None) -> dict:
    row = row or await asyncio.to_thread(current_card, email)
    now = now or datetime.now(timezone.utc)
    start, end, label = period_bounds(period, zone_for(row), now)
    existing = await asyncio.to_thread(_existing, row, email, period)
    if existing and (not refresh or existing.get("published_at")):
        return owner_payload(existing, row)
    def read():
        return (config.get_supabase().table("card_milestones").select("*").eq("card_id", row["id"])
                .eq("owner_email", email).gte("occurred_on", start.date().isoformat())
                .lte("occurred_on", (end.date() - timedelta(days=1)).isoformat())
                .order("occurred_on", desc=True).limit(MAX_HIGHLIGHTS).execute().data or [])
    milestones = await asyncio.to_thread(read)
    highlights = _highlights(row, milestones, start, end)
    identity = (row.get("card") or {}).get("identity") or {}
    login = github_handle_from_url((identity.get("links") or {}).get("github"))
    activity = {"items": [], "repositories": "not_connected"}
    count = None
    if login:
        count, activity = await asyncio.gather(
            fetch_period_contributions(login, start, min(end, now)),
            fetch_period_activity(login, start, min(end, now)))
    # Temporary outages must not erase evidence already fetched for this profile and period.
    if existing and login and existing["snapshot"].get("github_login") == login.lower():
        seen_ids = {h["id"] for h in activity["items"]}
        for h in existing["snapshot"]["highlights"]:
            if h["kind"] == "repository" and activity["repositories"] != "complete" and h["id"] not in seen_ids:
                activity["items"].append(h)
                seen_ids.add(h["id"])
    # A manual milestone linking the exact same GitHub evidence wins over its imported copy.
    evidence = {h["url"].rstrip("/") for h in highlights if h.get("url")}
    imported = [h for h in activity["items"] if h["url"].rstrip("/") not in evidence]
    # Give both sources room in the bounded snapshot without hiding manual milestones.
    room = max(0, MAX_HIGHLIGHTS - len(highlights))
    highlights.extend(imported[:room])
    if count is not None:
        highlights.append({"id": "github", "kind": "github", "title": "GitHub contributions", "count": count,
                           "url": f"https://github.com/{login}", "source": "github"})
    snapshot = {"name": (identity.get("name") or row["handle"])[:140], "label": label,
                "timezone": zone_for(row).key, "in_progress": now < end,
                "generated_at": now.isoformat(), "highlights": highlights,
                "github_available": count is not None,
                "github_login": login.lower() if login else None,
                "github_activity": {"repositories": activity["repositories"],
                                    "truncated": len(imported) > room},
                "history_note": "Includes newly created public GitHub repositories, contribution totals, and dated milestones you confirmed."}
    draft = await asyncio.to_thread(generate_social_caption, snapshot, default_caption(snapshot))
    snapshot["_caption_draft"] = draft
    values = {"snapshot": snapshot, "selected_ids": [h["id"] for h in highlights], "caption": draft["caption"]}
    def save():
        sb = config.get_supabase()
        if existing:
            # A concurrent publish must win over a refresh.
            sb.table("card_recaps").update(values).eq("id", existing["id"]).eq("owner_email", email).is_("published_at", "null").execute()
        else:
            sb.table("card_recaps").upsert({**values, "card_id": row["id"], "owner_email": email, "period": period},
                                          on_conflict="card_id,owner_email,period", ignore_duplicates=True).execute()
        return _existing(row, email, period)
    saved = await asyncio.to_thread(save)
    if not saved:
        raise HTTPException(503, "Could not save your recap. Please try again.")
    return owner_payload(saved, row)


def owned(email: str, recap_id: str) -> tuple[dict, dict]:
    rows = (config.get_supabase().table("card_recaps").select("*").eq("id", recap_id)
            .eq("owner_email", email).limit(1).execute().data or [])
    if rows:
        cards = (config.get_supabase().table("agent_profile_cards").select("*").eq("id", rows[0]["card_id"])
                 .neq("status", "merged").limit(1).execute().data or [])
        if cards and (cards[0].get("owner_email") or "").strip().lower() == email:
            return rows[0], cards[0]
    raise HTTPException(404, "Recap not found")


def owner_payload(recap: dict, row: dict) -> dict:
    return {k: recap.get(k) for k in ("id", "period", "snapshot", "selected_ids", "caption", "published_at", "created_at")} | {
        "handle": row["handle"], "can_publish": row["status"] == "published"}


def list_owned(email: str) -> dict:
    row = current_card(email)
    rows = (config.get_supabase().table("card_recaps").select("*").eq("card_id", row["id"])
            .eq("owner_email", email).order("period", desc=True).limit(36).execute().data or [])
    projects = [{"name": p.get("name", ""), "url": safe_url(p.get("url", ""))}
                for p in (row.get("card") or {}).get("projects") or [] if p.get("name")]
    return {"recaps": [owner_payload(r, row) for r in rows], "projects": projects,
            "periods": previous_periods(datetime.now(timezone.utc), zone_for(row)), "handle": row["handle"]}


def update(email: str, recap_id: str, selected_ids: list[str], caption: str, publish: bool) -> dict:
    recap, row = owned(email, recap_id)
    valid = {h["id"] for h in recap["snapshot"]["highlights"]}
    if not set(selected_ids) <= valid:
        raise HTTPException(422, "Choose highlights from this recap")
    if publish and (row["status"] != "published" or not selected_ids):
        raise HTTPException(422, "Publish your profile and select a highlight before sharing")
    if recap.get("published_at"):
        raise HTTPException(409, "Unpublish this recap before editing it")
    # Keep generated copy in sync when a highlight is hidden. User-written copy remains editable.
    snapshot = recap["snapshot"]
    original = (snapshot.get("_caption_draft") or {}).get("caption")
    selected = visible_snapshot({**recap, "selected_ids": selected_ids})
    generated = ((caption == recap["caption"] and caption in (original, default_caption(visible_snapshot(recap))))
                 or caption == default_caption(selected))
    if generated and set(selected_ids) != set(recap.get("selected_ids") or []):
        draft = generate_social_caption(selected, default_caption(selected))
        caption = draft["caption"]
        snapshot = {**snapshot, "_caption_draft": draft}
    changes = {"selected_ids": list(dict.fromkeys(selected_ids)), "caption": caption.strip(),
               "snapshot": snapshot,
               "published_at": datetime.now(timezone.utc).isoformat() if publish else None}
    result = (config.get_supabase().table("card_recaps").update(changes).eq("id", recap_id)
              .eq("owner_email", email).is_("published_at", "null").execute().data or [])
    if not result:
        raise HTTPException(409, "Recap changed in another session. Reload before saving.")
    return owner_payload(result[0], row)


def rewrite_caption(email: str, recap_id: str, selected_ids: list[str]) -> dict:
    recap, row = owned(email, recap_id)
    if recap.get("published_at"):
        raise HTTPException(409, "Unpublish this recap before editing it")
    valid = {h["id"] for h in recap["snapshot"]["highlights"]}
    if not selected_ids or not set(selected_ids) <= valid:
        raise HTTPException(422, "Select highlights from this recap before writing a caption")
    selected = visible_snapshot({**recap, "selected_ids": selected_ids})
    draft = generate_social_caption(selected, default_caption(selected))
    changes = {"selected_ids": list(dict.fromkeys(selected_ids)), "caption": draft["caption"],
               "snapshot": {**recap["snapshot"], "_caption_draft": draft}}
    result = (config.get_supabase().table("card_recaps").update(changes).eq("id", recap_id)
              .eq("owner_email", email).is_("published_at", "null").execute().data or [])
    if not result:
        raise HTTPException(409, "Recap changed in another session. Reload before saving.")
    return owner_payload(result[0], row)


def unpublish(email: str, recap_id: str) -> dict:
    recap, row = owned(email, recap_id)
    config.get_supabase().table("card_recaps").update({"published_at": None}).eq("id", recap_id).eq("owner_email", email).execute()
    return owner_payload({**recap, "published_at": None}, row)


def public(recap_id: str, handle: str) -> dict:
    rows = (config.get_supabase().table("card_recaps").select("*").eq("id", recap_id)
            .not_.is_("published_at", "null").limit(1).execute().data or [])
    if rows:
        r = rows[0]
        cards = (config.get_supabase().table("agent_profile_cards").select("id,handle,status,owner_email")
                 .eq("id", r["card_id"]).eq("handle", handle).eq("status", "published")
                 .limit(1).execute().data or [])
        if cards and (cards[0].get("owner_email") or "").strip().lower() == r["owner_email"]:
            return {"id": r["id"], "period": r["period"], "handle": handle, "snapshot": visible_snapshot(r),
                    "caption": r["caption"], "published_at": r["published_at"]}
    raise HTTPException(404, "Recap not found")


async def run_scheduled(now: datetime | None = None, dry_run: bool = False) -> dict:
    """Catch up the last complete month and quarter. Unique keys make repeated ticks safe."""
    now = now or datetime.now(timezone.utc)
    result = {"generated": 0, "existing": 0, "failed": 0, "dry_run": dry_run}
    offset = 0
    sb = config.get_supabase()
    while True:
        rows = await asyncio.to_thread(lambda: sb.table("agent_profile_cards").select("*").eq("status", "published")
                                       .not_.is_("owner_email", "null").order("id").range(offset, offset + PAGE_SIZE - 1).execute().data or [])
        for row in rows:
            email = row["owner_email"].strip().lower()
            for period in previous_periods(now, zone_for(row)):
                try:
                    existing = await asyncio.to_thread(_existing, row, email, period)
                    if existing:
                        result["existing"] += 1
                        recap = owner_payload(existing, row)
                    elif dry_run:
                        result["generated"] += 1
                        continue
                    else:
                        recap = await generate(email, period, row=row, now=now)
                        result["generated"] += 1
                    if not dry_run and recap["snapshot"]["highlights"]:
                        # Retried independently if notification storage was temporarily unavailable.
                        await asyncio.to_thread(lambda: sb.table("card_nudges").upsert({
                            "owner_email": email, "handle": row["handle"], "dedupe_key": f"recap:{recap['id']}",
                            "kind": "recap", "title": f"Your {recap['snapshot']['label']} recap is ready",
                            "href": f"/home/recaps?id={quote(recap['id'])}"},
                            on_conflict="owner_email,dedupe_key", ignore_duplicates=True).execute())
                except Exception:
                    logger.exception("recap generation failed card=%s period=%s", row["id"], period)
                    result["failed"] += 1
        if len(rows) < PAGE_SIZE:
            return result
        offset += PAGE_SIZE
