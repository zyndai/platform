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


def _classify_url(url: str) -> str:
    # Match on hostname only — substring matching on full URL allows bypass via
    # path components (e.g. http://evil.com/x.com/user would be misclassified).
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host in ("twitter.com", "x.com") or host.endswith((".twitter.com", ".x.com")):
        return "x"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    return "website"


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


async def _run_pipeline(
    job_id: str,
    github_handle: str | None,
    x_handle: str | None,
    resume_text: str | None,
    url_sources: list[str],
) -> None:
    try:
        github_data = None
        if github_handle:
            github_data = await github_scraper.fetch_github(github_handle)

        website_texts: list[str] = []
        x_texts: list[str] = []
        linkedin_texts: list[str] = []

        if url_sources:
            results = await asyncio.gather(*[_safe_fetch_url(u) for u in url_sources])
            for kind, text in results:
                if not text:
                    continue
                if kind == "x":
                    x_texts.append(text)
                elif kind == "linkedin":
                    linkedin_texts.append(text)
                else:
                    website_texts.append(text)

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
        set_ready(job_id, card)
    except Exception as exc:
        set_error(job_id, str(exc))


@router.post("/start")
async def start_onboard(
    github_handle: str | None = Form(None),
    x_handle: str | None = Form(None),
    website_url: str | None = Form(None),
    linktree_url: str | None = Form(None),
    social_url: str | None = Form(None),
    portfolio_url: str | None = Form(None),
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

    url_sources = [u for u in [website_url, linktree_url, social_url, portfolio_url] if u]

    if not github_handle and not x_handle and not url_sources and not resume_text:
        raise HTTPException(status_code=400, detail="At least one source is required")

    job_id = create_job(github_handle, x_handle)
    asyncio.create_task(
        _run_pipeline(job_id, github_handle, x_handle, resume_text, url_sources)
    )
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

    await asyncio.to_thread(
        cards_service.insert_card, card, job.handle_github, job.handle_x
    )
    await hooks.run_publish_hooks(card.id)
    return card.model_dump(mode="json")
