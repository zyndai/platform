import httpx

import config

INDEXNOW_ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
]
BING_SUBMIT_URL = (
    "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlbatch"
    "?apikey=" + config.BING_API_KEY
)


def profile_url(card_id: str) -> str:
    return f"{config.SITE_BASE_URL}/profile/{card_id}"


async def ping_indexnow(urls: list[str]) -> None:
    if not config.INDEXNOW_KEY:
        return
    body = {
        "host": config.SITE_BASE_URL.replace("https://", "").replace("http://", ""),
        "key": config.INDEXNOW_KEY,
        "keyLocation": f"{config.SITE_BASE_URL}/{config.INDEXNOW_KEY}.txt",
        "urlList": urls,
    }
    async with httpx.AsyncClient() as c:
        for endpoint in INDEXNOW_ENDPOINTS:
            try:
                await c.post(endpoint, json=body)
            except httpx.HTTPError:
                continue


async def submit_bing_urls(urls: list[str]) -> None:
    if not config.BING_API_KEY:
        return
    body = {"siteUrl": config.BING_SITE_URL, "urlList": urls}
    async with httpx.AsyncClient() as c:
        try:
            await c.post(BING_SUBMIT_URL, json=body)
        except httpx.HTTPError:
            return


async def run_publish_hooks(card_id: str) -> None:
    url = profile_url(card_id)
    await ping_indexnow([url, config.SITE_BASE_URL + "/directory"])
    await submit_bing_urls([url])
