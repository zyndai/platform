"""
Onboarding pipeline: the profile URLs the user pasted (and that scraped fine)
end up as the card's links, not the LLM's rewritten versions of them.
Scrapers and synthesis are mocked.
"""
import asyncio

from api import onboard as onboard_api
from models.card import CardSynthesis
from services.jobs import create_job, get_job


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
