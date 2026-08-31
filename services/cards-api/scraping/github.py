import httpx

import config

GITHUB_API = "https://api.github.com"


async def fetch_github(handle: str) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    async with httpx.AsyncClient(headers=headers) as c:
        user_resp = await c.get(f"{GITHUB_API}/users/{handle}")
        user_resp.raise_for_status()
        repos_resp = await c.get(
            f"{GITHUB_API}/users/{handle}/repos",
            params={"sort": "updated", "per_page": 30},
        )
        repos_resp.raise_for_status()

    return {"user": user_resp.json(), "repos": repos_resp.json()}
