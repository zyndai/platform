"""Onboarding pipeline — multi-URL input, auto-classifies to correct scraper."""
import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from models.card import AgentProfileCard
from publish import hooks
from scraping import github as github_scraper
from scraping import linkedin as linkedin_scraper
from scraping import website as website_scraper
from scraping import x as x_scraper
from scraping.resume import extract_resume_text
from services import cards as cards_service
from services.jobs import create_job, get_job, set_error, set_ready, utcnow
from synthesis.synthesize import synthesize_card

router = APIRouter()


class PublishRequest(BaseModel):
    card: dict
    user_answers: dict[str, str] = {}


def _classify_url(url: str) -> str:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host == "github.com" or host.endswith(".github.com"):
        return "github"
    if host in ("twitter.com", "x.com") or host.endswith((".twitter.com", ".x.com")):
        return "x"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    return "website"


def _handle_from_url(url: str) -> str | None:
    from urllib.parse import urlparse
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else None


async def _safe_fetch_url(url: str) -> tuple[str, str]:
    """Returns (kind, text). kind ∈ {'x', 'linkedin', 'website'}."""
    kind = _classify_url(url)
    try:
        if kind == "x":
            text = await x_scraper.fetch_x_profile(url)
        elif kind == "linkedin":
            text = await linkedin_scraper.fetch_linkedin_profile(url)
        else:
            text = await website_scraper.fetch_website(url)
        logger.info("scraped %s url=%s chars=%d", kind, url, len(text))
        return kind, text
    except Exception as exc:
        logger.warning("scrape failed kind=%s url=%s err=%s", kind, url, exc)
        return kind, ""


async def _run_pipeline(job_id: str, urls: list[str], resume_text: str | None) -> None:
    try:
        github_handle: str | None = None
        x_handle: str | None = None
        github_data = None

        github_urls = [u for u in urls if _classify_url(u) == "github"]
        other_urls = [u for u in urls if _classify_url(u) != "github"]

        if github_urls:
            github_handle = _handle_from_url(github_urls[0])
            if github_handle:
                github_data = await github_scraper.fetch_github(github_handle)

        x_urls = [u for u in other_urls if _classify_url(u) == "x"]
        if x_urls:
            x_handle = _handle_from_url(x_urls[0])

        # Expand Linktree / link-in-bio pages before scraping
        expanded: list[str] = []
        for u in other_urls:
            if website_scraper.is_linktree(u):
                try:
                    links = await website_scraper.fetch_linktree_links(u)
                    logger.info("linktree %s -> %d links", u, len(links))
                    expanded.extend(links)
                except Exception as exc:
                    logger.warning("linktree expand failed url=%s err=%s", u, exc)
            else:
                expanded.append(u)

        website_texts: list[str] = []
        x_texts: list[str] = []
        linkedin_texts: list[str] = []

        if expanded:
            results = await asyncio.gather(*[_safe_fetch_url(u) for u in expanded])
            for kind, text in results:
                if not text:
                    continue
                if kind == "x":
                    x_texts.append(text)
                elif kind == "linkedin":
                    linkedin_texts.append(text)
                else:
                    website_texts.append(text)

        # Exclude resume — user-uploaded private document; public scrapes only
        scrape_raw: dict = {
            "github": github_data,
            "linkedin": "\n\n".join(linkedin_texts) or None,
            "x": "\n\n".join(x_texts) or None,
            "website": "\n\n".join(website_texts) or None,
        }

        synth = synthesize_card(
            github_data,
            resume_text,
            website_text="\n\n".join(website_texts) or None,
            x_text="\n\n".join(x_texts) or None,
            linkedin_text="\n\n".join(linkedin_texts) or None,
        )
        card = cards_service.assemble_card(
            synth, github_data, github_handle, x_handle, bool(resume_text)
        )

        # Set handles before set_ready so publish sees them immediately
        job = get_job(job_id)
        if job:
            job.handle_github = github_handle
            job.handle_x = x_handle
        set_ready(job_id, card, scrape_raw=scrape_raw)
    except Exception as exc:
        set_error(job_id, str(exc))


@router.post("/start")
async def start_onboard(
    url: list[str] = Form(default=[]),
    resume: UploadFile | None = File(None),
):
    resume_text = None
    if resume is not None:
        suffix = ".pdf" if resume.content_type == "application/pdf" else ".docx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(await resume.read())
            path = f.name
        try:
            resume_text = extract_resume_text(path, resume.content_type)
        finally:
            os.unlink(path)

    if not url and not resume_text:
        raise HTTPException(status_code=400, detail="At least one source is required")

    job_id = create_job()
    asyncio.create_task(_run_pipeline(job_id, list(url), resume_text))
    return {"job_id": job_id}


@router.get("/{job_id}")
async def get_onboard_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "status": job.status,
        "card": job.card.model_dump(mode="json") if job.card else None,
        "error": job.error,
    }


@router.post("/{job_id}/publish")
async def publish_card(job_id: str, body: PublishRequest):
    job = get_job(job_id)
    if not job or not job.card:
        raise HTTPException(status_code=404, detail="job not found or not ready")

    card = AgentProfileCard.model_validate(body.card)
    now = utcnow()
    card.status = "published"
    card.updated_at = now
    card.review.status = "human_approved"
    card.review.reviewed_by = "user_self"
    card.review.reviewed_at = now

    user_intent = body.user_answers if body.user_answers else None

    handle = await asyncio.to_thread(
        cards_service.insert_card,
        card,
        job.handle_github,
        job.handle_x,
        job.scrape_raw,
        user_intent,
    )
    await hooks.run_publish_hooks(card.id, handle)
    return card.model_dump(mode="json")
