import asyncio
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from models.card import AgentProfileCard
from publish import hooks
from scraping import github as github_scraper
from scraping import website as website_scraper
from scraping.resume import extract_resume_text
from services import cards as cards_service
from services.jobs import create_job, get_job, set_error, set_ready, utcnow
from synthesis.synthesize import synthesize_card

router = APIRouter()


class PublishRequest(BaseModel):
    card: dict


async def _safe_fetch(url: str) -> str:
    try:
        return await website_scraper.fetch_website(url)
    except Exception:
        return ""


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

        website_text: str | None = None
        if url_sources:
            results = await asyncio.gather(*[_safe_fetch(u) for u in url_sources])
            combined = "\n\n".join(r for r in results if r)
            website_text = combined or None

        synth = synthesize_card(github_data, resume_text, website_text)
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
