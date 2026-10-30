"""A site that shows Jina Reader its bot check instead of the page: the check's text
must never reach the card, and the pasted link still does."""
import asyncio

import httpx
import pytest

from api import onboard as onboard_api
from models.card import CardSynthesis
from scraping import website
from services.jobs import create_job, get_job

# What r.jina.ai returned for a Product Hunt profile on 2026-10-30, handle changed.
CLOUDFLARE_PAGE = """Title: Just a moment...

URL Source: https://www.producthunt.com/@ada

Warning: This page maybe requiring CAPTCHA, please make sure you are authorized to access this page.

Markdown Content:
![Image 1: Icon for www.producthunt.com](https://www.producthunt.com/favicon.ico)
# www.producthunt.com

## Performing security verification

This website uses a security service to protect against malicious bots. This page is displayed while the website verifies you are not a bot.

## Verification successful. Waiting for www.producthunt.com to respond

Ray ID: `a52946ff7c7e45f7`

Performance and Security by [Cloudflare](https://www.cloudflare.com/?utm_source=challenge&utm_campaign=m)[Privacy](https://www.cloudflare.com/privacypolicy/)
"""

REAL_PAGE = "Title: Ada Lovelace\n\nMarkdown Content:\nAda writes compilers and teaches small teams to ship them."


@pytest.mark.parametrize("page", [
    CLOUDFLARE_PAGE,
    "Title: Attention Required! | Cloudflare\n\nMarkdown Content:\nSorry, you have been blocked",
    "Markdown Content:\nEnable JavaScript and cookies to continue",
    "Markdown Content:\n[Retry](https://ada.dev/?__cf_chl_tk=abc123)",
    "Markdown Content:\nChecking your browser before accessing ada.dev.",
    "Markdown Content:\n![x](https://geo.captcha-delivery.com/captcha/?initialCid=1)",
    "Markdown Content:\nPress & Hold to confirm you are a human (and not a bot).",
])
def test_bot_checks_are_recognised(page):
    assert website.is_bot_challenge(page)


def test_real_pages_are_not_bot_checks():
    assert not website.is_bot_challenge(REAL_PAGE)
    assert not website.is_bot_challenge("")
    # A long post that talks about Cloudflare's check is still a post.
    article = "Title: How bot checks work\n\nMarkdown Content:\n" + "Cloudflare shows 'Performing security verification' first. " * 80
    assert not website.is_bot_challenge(article)


def _serve(monkeypatch, pages: dict[str, str]) -> None:
    """Answer r.jina.ai/<url> from `pages`, through the real _jina_fetch."""
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        target = str(request.url).removeprefix(website._JINA_BASE)
        return httpx.Response(200, text=pages[target]) if target in pages else httpx.Response(404)

    monkeypatch.setattr(website.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))


def test_jina_fetch_refuses_to_return_a_bot_check(monkeypatch):
    _serve(monkeypatch, {"https://ada.dev": CLOUDFLARE_PAGE, "https://ada.dev/about": REAL_PAGE})
    with pytest.raises(website.BotChallengeError):
        asyncio.run(website._jina_fetch("https://ada.dev"))
    assert asyncio.run(website._jina_fetch("https://ada.dev/about")) == REAL_PAGE


def _build(monkeypatch, urls: list[str], pages: dict[str, str]) -> tuple[dict, object]:
    seen: dict = {}

    def fake_synthesize(*_a, **kwargs):
        seen["website_text"] = kwargs.get("website_text")
        return CardSynthesis(identity={"name": "Ada"})

    _serve(monkeypatch, pages)
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)
    job_id = create_job()
    asyncio.run(onboard_api._run_pipeline(job_id, urls, None))
    return seen, get_job(job_id)


def test_a_website_and_a_substack_behind_a_bot_check_become_links(monkeypatch):
    site, substack, real = "https://ada.dev/?ref=bio", "https://ada.substack.com", "https://ada-notes.example.com"
    seen, job = _build(monkeypatch, [site, substack, real], {site: CLOUDFLARE_PAGE, substack: CLOUDFLARE_PAGE, real: REAL_PAGE})

    assert job.error is None and job.url_warnings == []
    assert "security verification" not in seen["website_text"] and "Ada writes compilers" in seen["website_text"]
    for url in (site, substack):
        assert job.sources[url]["state"] == "done"
        assert job.sources[url]["preview"] == {"facts": ["Link added to your card"]}
    assert job.card.identity.links == {"website": "https://ada.dev/", "substack": "https://ada.substack.com"}


def test_a_bot_check_never_overrides_a_link_the_card_already_has(monkeypatch):
    def fake_synthesize(*_a, **_k):
        return CardSynthesis(identity={"name": "Ada", "links": {"website": "https://ada.example.com"}})

    _serve(monkeypatch, {"https://ada.dev": CLOUDFLARE_PAGE, "https://ada.example.com": REAL_PAGE})
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)
    job_id = create_job()
    asyncio.run(onboard_api._run_pipeline(job_id, ["https://ada.dev", "https://ada.example.com"], None))
    assert get_job(job_id).card.identity.links == {"website": "https://ada.example.com"}


def test_a_linktree_behind_a_bot_check_is_kept_as_a_link(monkeypatch):
    tree = "https://linktr.ee/ada"
    _, job = _build(monkeypatch, [tree, "https://ada.dev"], {tree: CLOUDFLARE_PAGE, "https://ada.dev": REAL_PAGE})
    assert job.url_warnings == []
    assert job.sources[tree]["state"] == "done"
    assert job.card.identity.links["linktree"] == tree


def test_only_bot_checks_still_cannot_build_a_card(monkeypatch):
    _, job = _build(monkeypatch, ["https://ada.dev"], {"https://ada.dev": CLOUDFLARE_PAGE})
    assert job.error and job.card is None


def test_a_producthunt_profile_is_a_link_on_the_card(monkeypatch):
    profile = "https://www.producthunt.com/@Ada/made?ref=share"
    seen, job = _build(monkeypatch, [profile, "https://ada.dev"], {profile: CLOUDFLARE_PAGE, "https://ada.dev": REAL_PAGE})

    assert job.error is None and job.url_warnings == []
    assert job.sources[profile]["kind"] == "producthunt" and job.sources[profile]["state"] == "done"
    assert job.card.identity.links == {"producthunt": "https://www.producthunt.com/@ada"}  # no second copy as "website"
    assert "security verification" not in seen["website_text"]


def test_producthunt_profiles_are_their_own_kind_and_product_pages_are_websites():
    assert onboard_api._classify_url("https://www.producthunt.com/@ada") == "producthunt"
    assert onboard_api._classify_url("https://www.producthunt.com/products/orbit") == "website"
    assert onboard_api._classify_url("https://www.producthunt.com/posts/orbit") == "website"
