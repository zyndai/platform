"""Re-scrape LinkedIn + X for every published card and patch stored fields."""

import asyncio
import sys

import config
from models.card import WritingSample
from scraping import linkedin as linkedin_scraper
from scraping import x as x_scraper
from services import cards as cards_service
from services.jobs import utcnow

_SEM = asyncio.Semaphore(2)


def _links(card: dict) -> dict:
    ident = card.get("identity") or {}
    return ident.get("links") or {}


def _linkedin_url(links: dict) -> str:
    u = (links.get("linkedin") or "").strip()
    if not u:
        return ""
    if u.startswith("http"):
        return u
    return f"https://www.linkedin.com/in/{u.lstrip('/')}"


def _x_url(links: dict) -> str:
    u = (links.get("x") or links.get("twitter") or "").strip()
    if not u:
        return ""
    if u.startswith("http"):
        return u
    handle = u.lstrip("@")
    return f"https://x.com/{handle}"


def _as_samples(raw) -> list[WritingSample]:
    out: list[WritingSample] = []
    for s in raw or []:
        try:
            out.append(s if isinstance(s, WritingSample) else WritingSample.model_validate(s))
        except Exception:
            continue
    return out


async def sync_one(row: dict) -> str:
    handle = row.get("handle") or ""
    card = row.get("card") or {}
    links = _links(card)
    li_url = _linkedin_url(links)
    x_url = _x_url(links)
    if not li_url and not x_url:
        return f"{handle}: skip (no linkedin/x)"

    li_posts = None
    x_posts = None
    li_avatar = None
    x_avatar = None
    changed = []

    async with _SEM:
        if li_url:
            try:
                _, stats = await linkedin_scraper.fetch_linkedin_profile(li_url)
            except Exception as exc:
                return f"{handle}: linkedin fail {type(exc).__name__}"
            jobs = (stats or {}).pop("work_experience_raw", None) if stats else None
            if jobs:
                card["work_experience"] = jobs
                changed.append(f"jobs={len(jobs)}")
            if stats:
                li_posts = stats.get("posts_raw")
                li_avatar = stats.get("avatar")
                ls = dict(card.get("linkedin_stats") or {})
                for k in ("connections", "posts", "avatar"):
                    if stats.get(k) is not None:
                        ls[k] = stats[k]
                if ls:
                    card["linkedin_stats"] = ls
                    changed.append("li-stats")

        if x_url:
            try:
                _, x_stats = await x_scraper.fetch_x_profile(x_url)
            except Exception as exc:
                changed.append(f"x-fail:{type(exc).__name__}")
                x_stats = None
            if x_stats:
                x_posts = x_stats.get("posts_raw")
                x_avatar = x_stats.get("avatar")
                xs = dict(card.get("x_stats") or {})
                for k in ("followers", "posts", "avatar", "handle", "impressions"):
                    if x_stats.get(k) is not None:
                        xs[k] = x_stats[k]
                if xs:
                    card["x_stats"] = xs
                    changed.append("x-stats")

    if cards_service.refresh_avatar(card, li_avatar, x_avatar):
        changed.append("avatar")

    if li_posts or x_posts:
        existing = _as_samples(card.get("writing_samples"))
        merged = cards_service.merge_scraped_posts(existing, x_posts, li_posts)
        card["writing_samples"] = [w.model_dump(mode="json") for w in merged]
        changed.append(f"posts={len(merged)}")

    if not changed:
        return f"{handle}: no new data"

    card["updated_at"] = utcnow()
    config.get_supabase().table("agent_profile_cards").update(
        {"card": card, "updated_at": card["updated_at"]}
    ).eq("handle", handle).execute()
    return f"{handle}: ok {' '.join(changed)}"


async def main() -> int:
    rows = (
        config.get_supabase()
        .table("agent_profile_cards")
        .select("handle,card")
        .eq("status", "published")
        .execute()
        .data
        or []
    )
    print(f"cards {len(rows)}", flush=True)
    results = await asyncio.gather(*(sync_one(r) for r in rows), return_exceptions=True)
    ok = 0
    for r in results:
        if isinstance(r, Exception):
            print(f"err {type(r).__name__}", flush=True)
            continue
        print(r, flush=True)
        if isinstance(r, str) and ": ok " in r:
            ok += 1
    print(f"synced {ok}/{len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
