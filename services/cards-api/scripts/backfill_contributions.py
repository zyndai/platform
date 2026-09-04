import asyncio
import re

import config
from models.card import AgentProfileCard
from scraping import github as github_scraper


def handle_from_url(url):
    if not url:
        return None
    m = re.search(r"github\.com/([^/]+)", url)
    return m.group(1) if m else None


async def backfill_one(row):
    card = AgentProfileCard.model_validate(row["card"])
    gh_url = (card.identity.links or {}).get("github")
    handle = handle_from_url(gh_url)
    if not handle:
        return None

    data = await github_scraper.fetch_github(handle)
    contrib = data.get("contribution_stats")
    total_commits = (data.get("stats") or {}).get("total_commits")
    if not contrib:
        return None

    card.contribution_stats = contrib
    if card.github_stats is not None:
        card.github_stats["total_commits"] = total_commits

    config.get_supabase().table("agent_profile_cards").update(
        {"card": card.model_dump(mode="json")}
    ).eq("id", row["id"]).execute()
    return contrib["total"]


async def main():
    rows = (
        config.get_supabase()
        .table("agent_profile_cards")
        .select("id,card")
        .eq("status", "published")
        .execute()
        .data or []
    )
    done = 0
    for row in rows:
        try:
            total = await backfill_one(row)
            if total is not None:
                done += 1
                print(f"updated {row['id']}: {total} contributions")
        except Exception as exc:
            print(f"failed {row['id']}: {exc}")
    print(f"done: {done} updated")


if __name__ == "__main__":
    asyncio.run(main())
