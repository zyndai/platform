"""Onboarding pipeline — multi-URL input, auto-classifies to correct scraper."""
import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

import config
from api.auth import verify_supabase_jwt
from models.card import AgentProfileCard, normalize_booking_url
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
    # Ignored: the owner comes from the verified session token. Kept so older
    # clients that still send it don't fail validation.
    owner_email: str | None = None
    custom_handle: str | None = None


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


def _profile_link(url: str) -> str:
    """A pasted profile URL as a card link: share-sheet query strings and fragments dropped."""
    from urllib.parse import urlparse
    return urlparse(url)._replace(query="", fragment="").geturl()


def _handle_from_url(url: str) -> str | None:
    from urllib.parse import urlparse
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else None


async def _safe_fetch_url(url: str) -> tuple[str, str, dict | None]:
    """Returns (kind, text, stats_or_None). kind ∈ {'x', 'linkedin', 'website'}."""
    kind = _classify_url(url)
    try:
        if kind == "x":
            text, stats = await x_scraper.fetch_x_profile(url)
        elif kind == "linkedin":
            text, stats = await linkedin_scraper.fetch_linkedin_profile(url)
        else:
            text = await website_scraper.fetch_website(url)
            stats = None
        logger.info("scraped %s url=%s chars=%d", kind, url, len(text))
        return kind, text, stats
    except Exception as exc:
        logger.warning("scrape failed kind=%s url=%s err=%s", kind, url, exc)
        return kind, "", None


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
                try:
                    github_data = await github_scraper.fetch_github(github_handle)
                except Exception as exc:
                    logger.warning("github scrape skipped handle=%s err=%s", github_handle, exc)
                    github_data = None
                    github_handle = None
                if github_data == {}:
                    logger.info("github user not found handle=%s — continuing without GitHub", github_handle)
                    job = get_job(job_id)
                    if job:
                        job.url_warnings.append({
                            "url": github_urls[0],
                            "message": f"GitHub user '{github_handle}' not found. Check the username and try again.",
                        })
                    github_data = None
                    github_handle = None

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
        x_stats_data: dict | None = None
        linkedin_stats_data: dict | None = None

        linkedin_url_used: str | None = None
        x_url_used: str | None = None
        if expanded:
            results = await asyncio.gather(*[_safe_fetch_url(u) for u in expanded])
            for (orig_url, (kind, text, stats)) in zip(expanded, results):
                if not text:
                    continue
                if kind == "x":
                    x_texts.append(text)
                    if stats and not x_stats_data:
                        x_stats_data = stats
                    if not x_url_used:
                        x_url_used = orig_url
                elif kind == "linkedin":
                    linkedin_texts.append(text)
                    if stats and not linkedin_stats_data:
                        linkedin_stats_data = stats
                    if not linkedin_url_used:
                        linkedin_url_used = orig_url
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

        # A profile URL the user gave us, and that scraped fine, beats the LLM's
        # rendering of it: the LLM "tidies" slugs (drops LinkedIn's -798a6a228
        # style suffix), which breaks the link and refresh-linkedin, which
        # re-scrapes whatever is stored here.
        if linkedin_url_used:
            synth.identity.links["linkedin"] = _profile_link(linkedin_url_used)
        if x_url_used:
            synth.identity.links["x"] = _profile_link(x_url_used)

        # Deterministic avatar priority: LinkedIn > X > GitHub. The LLM's guess
        # (if any) is overridden by real scraped photo URLs.
        synth.identity.avatar_url = cards_service.pick_avatar(
            (linkedin_stats_data or {}).get("avatar"),
            (x_stats_data or {}).get("avatar"),
            ((github_data or {}).get("user") or {}).get("avatar_url"),
        ) or synth.identity.avatar_url

        # Deterministic post injection: both platforms must appear even when
        # the LLM only picked one. posts_raw is a pipeline-internal key — pop
        # it so it never lands in the stored card stats.
        x_posts_raw = (x_stats_data or {}).pop("posts_raw", None) if x_stats_data else None
        li_posts_raw = (linkedin_stats_data or {}).pop("posts_raw", None) if linkedin_stats_data else None
        work_experience_raw = (linkedin_stats_data or {}).pop("work_experience_raw", None) if linkedin_stats_data else None
        synth.writing_samples = cards_service.merge_scraped_posts(
            synth.writing_samples, x_posts_raw, li_posts_raw
        )

        card = cards_service.assemble_card(
            synth, github_data, github_handle, x_handle, bool(resume_text),
            linkedin_scraped=bool(linkedin_texts),
            x_stats=x_stats_data,
            linkedin_stats=linkedin_stats_data,
            contribution_stats=github_data.get("contribution_stats") if github_data else None,
            work_experience=work_experience_raw or None,
        )

        # Set handles before set_ready so publish sees them immediately
        job = get_job(job_id)
        if job:
            job.handle_github = github_handle
            job.handle_x = x_handle
            job.linkedin_url = linkedin_url_used
        set_ready(job_id, card, scrape_raw=scrape_raw)
    except Exception as exc:
        set_error(job_id, str(exc))


@router.get("/claim-candidates")
async def claim_candidates(linkedin: str = Query("", max_length=500)):
    """S08 claim-first: published, unclaimed cards whose LinkedIn URL matches,
    so the UI can offer "claim it" instead of building a duplicate."""
    from services import cards as cards_service

    candidates = await asyncio.to_thread(cards_service.claim_candidates_by_linkedin, linkedin)
    return {"candidates": candidates}


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
        "url_warnings": job.url_warnings,
    }


@router.post("/{job_id}/publish")
async def publish_card(
    job_id: str,
    body: PublishRequest,
    authorization: str | None = Header(default=None),
):
    # Ownership comes only from a verified session. An anonymous publish creates
    # an unowned card plus a one-time claim token the publisher needs to claim it.
    principal = verify_supabase_jwt(authorization) if authorization else None
    owner_email = principal.email if principal else None
    if body.owner_email and body.owner_email != owner_email:
        logger.warning("publish: ignoring client-supplied owner_email for job=%s", job_id)
    claim_token, claim_token_hash = (None, None) if owner_email else cards_service.new_claim_token()

    job = get_job(job_id)
    if not job or not job.card:
        raise HTTPException(status_code=404, detail="job not found or not ready")

    # A card can never be recreated or replaced through publish once one
    # already exists for this owner (or, anonymously, for these social
    # handles) — point back at it instead. Refreshing specific fields on an
    # owned card has its own endpoints (cards.py's refresh-*).
    if principal:
        existing = await asyncio.to_thread(cards_service.get_card_by_owner, principal.email)
    else:
        existing = await asyncio.to_thread(
            cards_service.get_card_by_social_handle,
            job.handle_github,
            job.handle_x,
            # Match the form stored on cards: share-sheet query strings and
            # fragments dropped, same as _profile_link above.
            _profile_link(job.linkedin_url) if job.linkedin_url else None,
        )
    if existing:
        _, existing_handle = existing
        return {"existing": True, "handle": existing_handle}

    card = AgentProfileCard.model_validate(body.card)
    now = utcnow()
    card.status = "published"
    card.updated_at = now
    card.review.status = "human_approved"
    card.review.reviewed_by = "user_self"
    card.review.reviewed_at = now

    answers = body.user_answers
    if answers.get("working_on"):
        card.working_on = [x.strip() for x in answers["working_on"].split(",") if x.strip()]
    if answers.get("can_help"):
        card.can_help_with = [x.strip() for x in answers["can_help"].split(",") if x.strip()]
    if answers.get("connect_with"):
        card.connect_with = [x.strip() for x in answers["connect_with"].split(",") if x.strip()]
    if answers.get("love_talking"):
        card.love_talking_about = [x.strip() for x in answers["love_talking"].split(",") if x.strip()]
    # The user's own answer is authoritative. Extraction may have guessed a
    # location from the resume or LinkedIn while the questions were being
    # answered — an explicitly typed location always wins over the guess.
    # Whitespace-only answers are ignored so a stray entry can't wipe a
    # scraped location.
    if (answers.get("location") or "").strip():
        card.identity.location = answers["location"].strip()
    # Attribute assignment skips the model's validators, so normalize here.
    for key in ("calendly_url", "google_calendar_url"):
        if answers.get(key):
            setattr(card, key, normalize_booking_url(answers[key]))

    user_intent = answers if answers else None

    owner_user_id = principal.sub if principal and principal.iss == config.AAFO_ISSUER else None
    handle = await asyncio.to_thread(
        cards_service.insert_card,
        card,
        job.handle_github,
        job.handle_x,
        job.scrape_raw,
        user_intent,
        owner_email,
        body.custom_handle,
        claim_token_hash,
        owner_user_id,
    )
    card.handle = handle  # frontend reads published.handle for redirect
    await hooks.run_publish_hooks(card.id, handle)
    result = card.model_dump(mode="json")
    if claim_token:
        result["claim_token"] = claim_token  # shown once; send as X-Claim-Token to claim
    return result
