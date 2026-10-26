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
        assert cancel_job(job_id) is False  # nothing left to stop

    asyncio.run(scenario())
