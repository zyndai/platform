"""New public repositories for a recap period, using GitHub's actual creation dates."""
import asyncio
from datetime import datetime

import httpx

import config
from scraping.github import GITHUB_API, _HANDLE_RE, _REPO_RE

PAGE_SIZE = 100
REPOSITORY_PAGES = 5
SCAN_TIMEOUT_SECONDS = 20


def _timestamp(raw):
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


async def fetch_period_activity(handle: str, start: datetime, end: datetime) -> dict:
    """Owned, currently public repositories created within [start, end).

    A repository becoming public later does not make it newly created. Stable URLs
    deduplicate pagination overlaps. Partial scans never imply zero repositories.
    """
    result = {"items": [], "repositories": "unavailable"}
    if not _HANDLE_RE.fullmatch(handle or "") or end <= start:
        return result
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    seen = set()
    try:
        async with asyncio.timeout(SCAN_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=False) as client:
                for page in range(1, REPOSITORY_PAGES + 1):
                    response = await client.get(f"{GITHUB_API}/users/{handle}/repos", params={
                        "type": "owner", "sort": "created", "direction": "desc",
                        "per_page": PAGE_SIZE, "page": page,
                    })
                    response.raise_for_status()
                    repos = response.json()
                    if not isinstance(repos, list):
                        raise ValueError("Invalid repository response")
                    if result["repositories"] == "unavailable":
                        result["repositories"] = "complete"
                    reached_older = False
                    for repo in repos:
                        if not isinstance(repo, dict):
                            result["repositories"] = "partial"
                            continue
                        at = _timestamp(repo.get("created_at"))
                        if not at:
                            result["repositories"] = "partial"
                            continue
                        if at < start:
                            reached_older = True
                        name = repo.get("full_name")
                        if (repo.get("private") is not False or not isinstance(name, str)
                                or not _REPO_RE.fullmatch(name) or name.split("/")[0].lower() != handle.lower()
                                or not start <= at < end):
                            continue
                        url = f"https://github.com/{name}"
                        if url in seen:
                            continue
                        seen.add(url)
                        result["items"].append({"id": f"github:repository:{url}", "kind": "repository",
                                                "title": name, "url": url,
                                                "date": at.astimezone(start.tzinfo).date().isoformat(),
                                                "source": "github"})
                    # Creation-descending ordering lets historical scans stop safely here.
                    if len(repos) < PAGE_SIZE or reached_older:
                        break
                    if page == REPOSITORY_PAGES:
                        result["repositories"] = "partial"
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, TimeoutError):
        if result["repositories"] != "unavailable":
            result["repositories"] = "partial"
    result["items"].sort(key=lambda item: (item["date"], item["id"]), reverse=True)
    return result
