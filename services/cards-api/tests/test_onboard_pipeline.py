"""
Onboarding pipeline: the profile URLs the user pasted (and that scraped fine)
end up as the card's links, not the LLM's rewritten versions of them.
Scrapers and synthesis are mocked.
"""
import asyncio

from api import onboard as onboard_api
from models.card import CardSynthesis
from services.jobs import cancel_job, create_job, get_job


def test_scraped_profile_urls_override_llm_links(monkeypatch):
    li_url = "https://www.linkedin.com/in/dilnawaz-hossain-asrafi-798a6a228/?utm_source=share&utm_medium=android_app"
    x_url = "https://x.com/walker_nb"

    async def fake_fetch(url):
        kind = onboard_api._classify_url(url)
        return kind, f"{kind} profile text", None

    async def fake_github(handle):
        return {"user": {"login": handle, "html_url": f"https://github.com/{handle}"}}

    # The LLM "tidies" every link it saw: drops LinkedIn's suffix, guesses the rest.
    def fake_synthesize(*_a, **_k):
        return CardSynthesis(identity={"name": "Dilnawaz", "links": {
            "linkedin": "https://www.linkedin.com/in/dilnawaz-hossain-asrafi",
            "github": "https://github.com/walkernullbyte",
            "x": "https://x.com/walker",
        }})

    monkeypatch.setattr(onboard_api, "_safe_fetch_url", fake_fetch)
    monkeypatch.setattr(onboard_api.github_scraper, "fetch_github", fake_github)
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)

    job_id = create_job()
    asyncio.run(onboard_api._run_pipeline(job_id, [li_url, "https://github.com/walker-null-byte", x_url], None))

    job = get_job(job_id)
    assert job.error is None
    links = job.card.identity.links
    assert links["linkedin"] == "https://www.linkedin.com/in/dilnawaz-hossain-asrafi-798a6a228/"
    assert links["github"] == "https://github.com/walker-null-byte"
    assert links["x"] == "https://x.com/walker_nb"


def test_each_source_reports_its_state_and_preview(monkeypatch):
    """The create page fills in source by source, so a failed source must not stay 'reading'."""
    seen_during_synthesis: dict = {}

    async def fake_fetch(url):
        if "broken" in url:
            return "website", "", None
        return "linkedin", "Name: Ada Lovelace\nHeadline: Engineer\n", {"avatar": "https://cdn.example/a.jpg"}

    async def fake_github(handle):
        return {"user": {"login": handle, "name": "Ada", "avatar_url": "https://avatars.example/a"}, "stats": {"total_repos": 3}}

    def fake_synthesize(*_a, **_k):
        # The synthesis thread runs after scraping: sources are final, stage says so.
        seen_during_synthesis["stage"] = get_job(job_id).stage
        seen_during_synthesis["states"] = {u: s["state"] for u, s in get_job(job_id).sources.items()}
        return CardSynthesis(identity={"name": "Ada"})

    monkeypatch.setattr(onboard_api, "_safe_fetch_url", fake_fetch)
    monkeypatch.setattr(onboard_api.github_scraper, "fetch_github", fake_github)
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)

    job_id = create_job()
    urls = [
        "https://github.com/ada",
        "https://github.com/ada-second",
        "https://www.linkedin.com/in/ada",
        "https://broken.example.com",
    ]
    asyncio.run(onboard_api._run_pipeline(job_id, urls, None))

    assert seen_during_synthesis["stage"] == "synthesizing"
    assert seen_during_synthesis["states"] == {
        "https://github.com/ada": "done",
        "https://github.com/ada-second": "skipped",
        "https://www.linkedin.com/in/ada": "done",
        "https://broken.example.com": "failed",
    }
    job = get_job(job_id)
    assert job.stage == "ready"
    assert job.sources["https://github.com/ada"]["preview"]["name"] == "Ada"
    assert job.sources["https://www.linkedin.com/in/ada"]["preview"]["headline"] == "Engineer"
    assert job.sources["https://broken.example.com"]["preview"] == {}


def test_status_endpoint_exposes_stage_and_sources():
    job_id = create_job()
    from services.jobs import set_source
    set_source(job_id, "https://github.com/ada", "github", "reading")

    status = asyncio.run(onboard_api.get_onboard_status(job_id))
    assert status["stage"] == "reading"
    assert status["sources"] == [{"url": "https://github.com/ada", "kind": "github", "state": "reading", "preview": {}}]


def test_cancel_stops_a_running_build(monkeypatch):
    started = asyncio.Event()

    async def slow_fetch(url):
        started.set()
        await asyncio.sleep(30)
        return "website", "text", None

    monkeypatch.setattr(onboard_api, "_safe_fetch_url", slow_fetch)

    async def scenario():
        job_id = create_job()
        job = get_job(job_id)
        job.task = asyncio.create_task(onboard_api._run_pipeline(job_id, ["https://example.com"], None))
        await started.wait()
        assert cancel_job(job_id) is True
        try:
            await job.task
        except asyncio.CancelledError:
            pass
        assert job.task.cancelled()
        assert job.status == "cancelled"  # not "running" forever
        assert cancel_job(job_id) is False  # nothing left to stop

    asyncio.run(scenario())


def test_a_cancelled_build_never_reaches_the_model(monkeypatch):
    calls: list[str] = []

    async def fake_fetch(url):
        return "website", "page text", None

    def fake_synthesize(*_a, **_k):
        calls.append("synthesize")
        return CardSynthesis(identity={"name": "Ada"})

    monkeypatch.setattr(onboard_api, "_safe_fetch_url", fake_fetch)
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)

    job_id = create_job()
    # The flag cancel_job sets, as if the cancellation itself had been lost on the way.
    get_job(job_id).cancelled = True
    asyncio.run(onboard_api._run_pipeline(job_id, ["https://example.com"], None))

    assert calls == []
    assert get_job(job_id).status == "cancelled"


def test_finished_jobs_are_evicted_after_their_ttl():
    from services.jobs import JOB_TTL_SECONDS

    old_id = create_job()
    running_id = create_job()

    async def never_done():
        await asyncio.sleep(3600)

    async def scenario():
        get_job(running_id).task = asyncio.create_task(never_done())
        for job_id in (old_id, running_id):
            get_job(job_id).created_at -= JOB_TTL_SECONDS + 1
        fresh_id = create_job()
        try:
            assert get_job(old_id) is None
            assert get_job(running_id) is not None  # its pipeline timeout ends it, not the TTL
            assert get_job(fresh_id) is not None
        finally:
            get_job(running_id).task.cancel()

    asyncio.run(scenario())


def test_start_is_rate_limited_per_ip(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    monkeypatch.setattr(onboard_api, "_start_hits", onboard_api.defaultdict(onboard_api.deque))
    started: list[str] = []

    async def fake_pipeline(job_id, urls, resume_text):
        started.append(job_id)

    monkeypatch.setattr(onboard_api, "_run_pipeline", fake_pipeline)

    def request(ip: str) -> Request:
        return Request({"type": "http", "method": "POST", "path": "/onboard/start", "headers": [
            (b"x-forwarded-for", ip.encode()),
        ]})

    async def start(ip: str):
        # Called directly, so FastAPI's Form()/File() defaults must be passed explicitly.
        await onboard_api.start_onboard(request(ip), url=["https://example.com"], resume=None, source=None, ref=None, utm=None)

    async def scenario():
        for _ in range(onboard_api._MAX_STARTS_PER_WINDOW):
            await start("203.0.113.7")
        try:
            await start("203.0.113.7")
        except HTTPException as exc:
            assert exc.status_code == 429
        else:
            raise AssertionError("the build after the limit must be refused")
        # Another network is not held up by the first one.
        await start("198.51.100.2")
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert len(started) == onboard_api._MAX_STARTS_PER_WINDOW + 1


def test_newsletter_and_portfolio_sources_become_posts_and_a_gallery(monkeypatch):
    """A Substack's posts and a Behance profile's projects are proof too: they go on the card without the LLM."""
    post_url = "https://ada.substack.com/p/how-i-hire"
    cover = "https://mir-s3-cdn-cf.behance.net/projects/202/aaa.jpg"

    async def fake_fetch(url):
        if "substack" in url:
            posts = [{"platform": "substack", "excerpt": "How I hire designers who ship", "url": post_url, "posted_at": ""}]
            return "writing", "Title: Ada's notes\n\nMarkdown Content:\nPlain words about hiring designers who ship.", {"posts_raw": posts}
        gallery = [{"title": "Orbit", "url": "https://www.behance.net/gallery/1/Orbit", "image_url": cover, "source": "behance"}]
        return "portfolio", "Title: Ada on Behance", {"gallery": gallery}

    def fake_synthesize(*_a, **_k):
        return CardSynthesis(persona="Product Design", identity={"name": "Ada"})

    monkeypatch.setattr(onboard_api, "_safe_fetch_url", fake_fetch)
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)

    job_id = create_job()
    urls = ["https://ada.substack.com", "https://www.behance.net/ada"]
    asyncio.run(onboard_api._run_pipeline(job_id, urls, None))

    job = get_job(job_id)
    assert job.error is None
    assert [(w.platform, w.url) for w in job.card.writing_samples] == [("substack", post_url)]
    assert [(g.title, g.image_url) for g in job.card.work_gallery] == [("Orbit", cover)]
    assert job.persona == "product_design"

    substack = job.sources["https://ada.substack.com"]
    assert substack["kind"] == "writing" and substack["preview"]["facts"] == ["1 recent posts"]
    assert substack["preview"]["posts"] == ["How I hire designers who ship"]
    behance = job.sources["https://www.behance.net/ada"]
    assert behance["kind"] == "portfolio" and behance["preview"]["images"] == [cover]

    status = asyncio.run(onboard_api.get_onboard_status(job_id))
    assert status["persona"] == "product_design"


def test_source_kinds_are_classified_by_host():
    classify = onboard_api._classify_url
    assert classify("https://ada.substack.com/archive") == "writing"
    assert classify("https://www.behance.net/ada") == "portfolio"
    assert classify("https://dribbble.com/ada") == "portfolio"
    assert classify("https://github.com/ada") == "github"
    assert classify("https://ada.dev") == "website"


def test_producthunt_launches_become_projects_and_the_profile_a_link(monkeypatch):
    launch = {"name": "Orbit", "tagline": "Calendar for remote teams", "url": "https://www.producthunt.com/products/orbit",
              "upvotes": 412, "source": "producthunt"}

    async def fake_fetch(url):
        return "producthunt", "Title: Ada on Product Hunt", {"launches": [launch]}

    monkeypatch.setattr(onboard_api, "_safe_fetch_url", fake_fetch)
    monkeypatch.setattr(onboard_api, "synthesize_card", lambda *_a, **_k: CardSynthesis(identity={"name": "Ada"}))

    job_id = create_job()
    url = "https://www.producthunt.com/@Ada/made?ref=share"
    asyncio.run(onboard_api._run_pipeline(job_id, [url], None))

    job = get_job(job_id)
    assert job.error is None
    assert [(p.name, p.description, p.source) for p in job.card.projects] == [
        ("Orbit", "Calendar for remote teams · 412 upvotes", "producthunt"),
    ]
    assert job.card.identity.links["producthunt"] == "https://www.producthunt.com/@ada"
    assert job.sources[url]["kind"] == "producthunt" and job.sources[url]["preview"]["facts"] == ["1 launch"]


def test_a_producthunt_bot_check_keeps_the_link_and_stays_out_of_synthesis(monkeypatch):
    """Product Hunt usually answers the reader with Cloudflare's check: no error, no boilerplate in the card."""
    seen: dict = {}

    async def fake_page(url):
        if "producthunt" in url:
            page = "Title: Just a moment...\n\nMarkdown Content:\n## Performing security verification\n"
            return page, page
        return "Ada writes compilers.", "Ada writes compilers."

    def fake_synthesize(*_a, **kwargs):
        seen["website_text"] = kwargs.get("website_text")
        return CardSynthesis(identity={"name": "Ada"})

    monkeypatch.setattr(onboard_api.website_scraper, "fetch_page", fake_page)
    monkeypatch.setattr(onboard_api, "synthesize_card", fake_synthesize)

    job_id = create_job()
    ph = "https://www.producthunt.com/@ada"
    asyncio.run(onboard_api._run_pipeline(job_id, [ph, "https://ada.dev"], None))

    job = get_job(job_id)
    assert job.error is None and job.url_warnings == []
    assert seen["website_text"] == "Ada writes compilers."
    assert job.sources[ph]["state"] == "done"
    assert job.sources[ph]["preview"] == {"facts": ["Link added to your card"]}
    assert job.card.identity.links["producthunt"] == ph
    assert job.card.projects == []


def test_producthunt_profiles_are_their_own_kind_and_product_pages_are_websites():
    classify = onboard_api._classify_url
    assert classify("https://www.producthunt.com/@ada") == "producthunt"
    assert classify("https://www.producthunt.com/products/orbit") == "website"
