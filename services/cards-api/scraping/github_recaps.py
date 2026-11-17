"""Dated public GitHub evidence for recaps; never infer dates from recent events.

REST works without a token for public data. The existing GITHUB_TOKEN raises rate limits.
Bounded scans report partial coverage instead of claiming exhaustive activity counts.
"""
import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

import config
from scraping.github import GITHUB_API, _HANDLE_RE, _REPO_RE

REPOSITORY_LIMIT = 30
RELEASE_PAGES = 2
PR_PAGES = 2
PAGE_SIZE = 30
CONCURRENCY = 4
SCAN_TIMEOUT_SECONDS = 40


def _timestamp(raw):
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def _title(raw):
    return " ".join(str(raw or "").split())[:140]


async def fetch_period_activity(handle: str, start: datetime, end: datetime) -> dict:
    """Public releases authored in owned repos and authored PRs merged in any public repo.

    Each kind has an independent availability status. Stable evidence URLs dedupe pagination
    overlaps; timestamps are checked again locally against [start, end), in the owner's zone.
    """
    result = {"items": [], "releases": "unavailable", "pull_requests": "unavailable"}
    if not _HANDLE_RE.fullmatch(handle or "") or end <= start:
        return result
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    semaphore = asyncio.Semaphore(CONCURRENCY)
    seen = set()
    async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=False) as client:
        async def get(path, **params):
            async with semaphore:
                response = await client.get(f"{GITHUB_API}{path}", params=params)
                response.raise_for_status()
                return response.json()

        def add(kind, repo, title, at, url):
            at = _timestamp(at)
            if not at or not start <= at < end or not title or url in seen:
                return
            seen.add(url)
            result["items"].append({"id": f"github:{kind}:{url}", "kind": kind,
                                    "title": f"{repo}: {title}"[:140], "url": url,
                                    "date": at.astimezone(start.tzinfo).date().isoformat(),
                                    "source": "github"})

        async def releases():
            # Ask for one extra repository to detect truncation without following remote URLs.
            repos = await get(f"/users/{handle}/repos", type="owner", sort="updated",
                              direction="desc", per_page=REPOSITORY_LIMIT + 1, page=1)
            if not isinstance(repos, list):
                raise ValueError("Invalid repository response")
            result["releases"] = "partial" if len(repos) > REPOSITORY_LIMIT else "complete"

            async def scan(repo):
                name = repo.get("full_name", "")
                if (repo.get("private") is not False or not _REPO_RE.fullmatch(name)
                        or name.split("/")[0].lower() != handle.lower()):
                    return
                try:
                    for page in range(1, RELEASE_PAGES + 1):
                        rows = await get(f"/repos/{name}/releases", per_page=100, page=page)
                        if not isinstance(rows, list):
                            raise ValueError("Invalid releases response")
                        for release in rows:
                            if (release.get("draft") or release.get("prerelease")
                                    or (release.get("author") or {}).get("login", "").lower() != handle.lower()):
                                continue
                            tag = release.get("tag_name")
                            if not isinstance(tag, str) or not tag:
                                continue
                            add("release", name, _title(release.get("name") or tag), release.get("published_at"),
                                f"https://github.com/{name}/releases/tag/{quote(tag, safe='')}")
                        # Release ordering uses creation, not publication. Do not stop on an old date.
                        if len(rows) < 100:
                            break
                        if page == RELEASE_PAGES:
                            result["releases"] = "partial"
                except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                    result["releases"] = "partial"
            await asyncio.gather(*(scan(repo) for repo in repos[:REPOSITORY_LIMIT]))

        async def pull_requests():
            # Broaden to UTC dates for search, then filter exact merge timestamps locally.
            first = start.astimezone(timezone.utc).date().isoformat()
            last = end.astimezone(timezone.utc).date().isoformat()
            query = f"is:pr is:merged is:public author:{handle} merged:{first}..{last}"
            for page in range(1, PR_PAGES + 1):
                body = await get("/search/issues", q=query, sort="updated", order="desc", per_page=PAGE_SIZE, page=page)
                rows = body.get("items")
                if not isinstance(rows, list):
                    raise ValueError("Invalid search response")
                if result["pull_requests"] == "unavailable":
                    result["pull_requests"] = "complete"
                if body.get("incomplete_results") or body.get("total_count", 0) > PR_PAGES * PAGE_SIZE:
                    result["pull_requests"] = "partial"

                async def scan(item):
                    # Search is public-only, but verify repository privacy and authorship from
                    # the actual PR too. Search results alone do not guarantee an exact merged_at.
                    match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([0-9]+)", item.get("html_url", ""))
                    if not match or not _REPO_RE.fullmatch(match[1]):
                        result["pull_requests"] = "partial"
                        return
                    repo, number = match.groups()
                    try:
                        pr = await get(f"/repos/{repo}/pulls/{number}")
                        if ((pr.get("base") or {}).get("repo", {}).get("private") is not False
                                or (pr.get("user") or {}).get("login", "").lower() != handle.lower()):
                            return
                        add("pull_request", repo, _title(pr.get("title")), pr.get("merged_at"),
                            f"https://github.com/{repo}/pull/{number}")
                    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                        result["pull_requests"] = "partial"
                await asyncio.gather(*(scan(item) for item in rows))
                if len(rows) < PAGE_SIZE:
                    break

        async def run(kind, action):
            try:
                async with asyncio.timeout(SCAN_TIMEOUT_SECONDS):
                    await action()
            except (httpx.HTTPError, ValueError, TypeError, AttributeError, TimeoutError):
                if result[kind] != "unavailable":
                    result[kind] = "partial"

        await asyncio.gather(run("releases", releases), run("pull_requests", pull_requests))
    result["items"].sort(key=lambda item: (item["date"], item["id"]), reverse=True)
    return result
