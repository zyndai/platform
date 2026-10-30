"""Onboarding pipeline — multi-URL input, auto-classifies to correct scraper."""
import asyncio
import logging
import os
import tempfile
import time
from collections import defaultdict, deque

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
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
from scraping import sites as site_scraper
from scraping.resume import extract_resume_text
from services import cards as cards_service
from services.jobs import (
    cancel_job, create_job, get_job, set_cancelled, set_error, set_ready, set_source, set_stage, utcnow,
)
from services.source_preview import build_preview
from synthesis.synthesize import synthesize_card

router = APIRouter()
SOURCE_TIMEOUT_SECONDS = 60
PIPELINE_TIMEOUT_SECONDS = 180

# Per-IP sliding window on /start. Every build scrapes each source and makes a
# paid model call, and the endpoint is public. Room for someone pasting links one
# at a time and rebuilding a few times, shared office networks included.
_START_WINDOW_SECONDS = 10 * 60
_MAX_STARTS_PER_WINDOW = 20
_start_hits: dict[str, deque[float]] = defaultdict(deque)


def _start_rate_limited(key: str) -> bool:
    now = time.monotonic()
    q = _start_hits[key]
    while q and now - q[0] > _START_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _MAX_STARTS_PER_WINDOW:
        return True
    q.append(now)
    if len(_start_hits) > 10_000:  # bound memory: drop every key
        _start_hits.clear()
    return False


def _source_warning(job_id: str, url: str, code: str = "inaccessible") -> None:
    job = get_job(job_id)
    if job and not any(w["url"] == url for w in job.url_warnings):
        job.url_warnings.append({
            "url": url, "code": code,
            "message": "This source timed out. Retry it or continue with other sources." if code == "timeout" else
                       "This profile could not be read. Check that it is public, replace the URL, or continue with other sources.",
        })


async def _fetch_source(job_id: str, url: str) -> tuple[str, str, dict | None]:
    kind = _classify_url(url)
    try:
        result = await asyncio.wait_for(_safe_fetch_url(url), SOURCE_TIMEOUT_SECONDS)
    except TimeoutError:
        _source_warning(job_id, url, "timeout")
        set_source(job_id, url, kind, "failed")
        return kind, "", None
    kind, text, stats = result
    # A page behind a bot check gave us nothing to read, but it is still the person's link.
    if text or (stats or {}).get("link_only"):
        set_source(job_id, url, kind, "done", build_preview(kind, text, stats))
    else:
        _source_warning(job_id, url)
        set_source(job_id, url, kind, "failed")
    return result


class PublishRequest(BaseModel):
    card: dict
    user_answers: dict[str, str] = {}
    # Ignored: the owner comes from the verified session token. Kept so older
    # clients that still send it don't fail validation.
    owner_email: str | None = None
    custom_handle: str | None = None
    # S04 attribution (from zynd_attr cookie). Invalid values are dropped.
    source: str | None = None
    ref: str | None = None
    utm: dict | None = None
    created_via: str | None = None


def _classify_url(url: str) -> str:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host == "github.com" or host.endswith(".github.com"):
        return "github"
    if host in ("twitter.com", "x.com") or host.endswith((".twitter.com", ".x.com")):
        return "x"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if site_scraper.producthunt_maker(url):
        return "producthunt"
    if site_scraper.is_writing_url(url):
        return "writing"
    if site_scraper.portfolio_platform(url):
        return "portfolio"
    return "website"


def _profile_link(url: str) -> str:
    """A pasted profile URL as a card link: share-sheet query strings and fragments dropped."""
    from urllib.parse import urlparse
    return urlparse(url)._replace(query="", fragment="").geturl()


def _link_key(url: str) -> str:
    """The identity.links key for a pasted page the card can only link to."""
    if website_scraper.is_linktree(url):
        return "linktree"
    if site_scraper.producthunt_maker(url):
        return "producthunt"
    return (
        site_scraper.writing_platform(url) or ("blog" if site_scraper.is_writing_url(url) else None)
        or site_scraper.portfolio_platform(url) or "website"
    )


def _handle_from_url(url: str) -> str | None:
    from urllib.parse import urlparse
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else None


async def _safe_fetch_url(url: str) -> tuple[str, str, dict | None]:
    """Returns (kind, text, stats_or_None). kind ∈ {'x', 'linkedin', 'producthunt', 'writing', 'portfolio', 'website'}.

    For a newsletter / blog / design portfolio, stats holds what scraping/sites.py
    found on the page: `posts_raw` (post links) and/or `gallery` (project tiles).
    A page that showed Jina a bot check gives no text and `{"link_only": True}`."""
    kind = _classify_url(url)
    try:
        if kind == "x":
            text, stats = await x_scraper.fetch_x_profile(url)
        elif kind == "linkedin":
            text, stats = await linkedin_scraper.fetch_linkedin_profile(url)
        else:
            text, markdown = await website_scraper.fetch_page(url)
            found = {
                "posts_raw": site_scraper.extract_posts(markdown, url),
                "gallery": site_scraper.extract_gallery(markdown, url),
            }
            stats = {k: v for k, v in found.items() if v} or None
        logger.info("scraped %s url=%s chars=%d", kind, url, len(text))
        return kind, text, stats
    except website_scraper.BotChallengeError:
        logger.info("bot check instead of page kind=%s url=%s", kind, url)
        return kind, "", {"link_only": True}
    except Exception as exc:
        logger.warning("scrape failed kind=%s url=%s err=%s", kind, url, exc)
        return kind, "", None


async def _run_pipeline(job_id: str, urls: list[str], resume_text: str | None) -> None:
    try:
        await asyncio.wait_for(_build_pipeline(job_id, urls, resume_text), PIPELINE_TIMEOUT_SECONDS)
    except TimeoutError:
        set_error(job_id, "Building your card took too long. Your inputs are kept; retry or use fewer sources.")
    except asyncio.CancelledError:
        set_cancelled(job_id)
        raise


async def _build_pipeline(job_id: str, urls: list[str], resume_text: str | None) -> None:
    try:
        github_handle: str | None = None
        x_handle: str | None = None
        github_data = None

        github_urls = [u for u in urls if _classify_url(u) == "github"]
        other_urls = [u for u in urls if _classify_url(u) != "github"]

        # The page lists every pasted source as soon as the build starts and
        # watches each one move to done / failed. Only the first GitHub profile
        # is read; the rest are shown as skipped rather than left "reading".
        for u in urls:
            set_source(job_id, u, _classify_url(u), "reading")
        for extra in github_urls[1:]:
            set_source(job_id, extra, "github", "skipped")

        if github_urls:
            github_handle = _handle_from_url(github_urls[0])
            if github_handle:
                try:
                    github_data = await asyncio.wait_for(github_scraper.fetch_github(github_handle), SOURCE_TIMEOUT_SECONDS)
                except Exception as exc:
                    _source_warning(job_id, github_urls[0], "timeout" if isinstance(exc, TimeoutError) else "failed")
                    set_source(job_id, github_urls[0], "github", "failed")
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
                    set_source(job_id, github_urls[0], "github", "failed")
                    github_data = None
                    github_handle = None
                elif github_data:
                    set_source(job_id, github_urls[0], "github", "done", build_preview("github", github=github_data))

        x_urls = [u for u in other_urls if _classify_url(u) == "x"]
        if x_urls:
            x_handle = _handle_from_url(x_urls[0])

        # Pages behind a bot check: nothing to read, so the card links to them instead.
        link_only_urls: list[str] = []

        # Expand Linktree / link-in-bio pages before scraping
        expanded: list[str] = []
        for u in other_urls:
            if website_scraper.is_linktree(u):
                try:
                    links = await asyncio.wait_for(website_scraper.fetch_linktree_links(u), SOURCE_TIMEOUT_SECONDS)
                    logger.info("linktree %s -> %d links", u, len(links))
                    expanded.extend(links)
                    set_source(job_id, u, "website", "done")
                    for link in links:
                        set_source(job_id, link, _classify_url(link), "reading")
                except website_scraper.BotChallengeError:
                    link_only_urls.append(u)
                    set_source(job_id, u, "website", "done", build_preview("website", "", {"link_only": True}))
                    logger.info("bot check instead of linktree url=%s", u)
                except Exception as exc:
                    _source_warning(job_id, u, "timeout" if isinstance(exc, TimeoutError) else "failed")
                    set_source(job_id, u, "website", "failed")
                    logger.warning("linktree expand failed url=%s err=%s", u, exc)
            else:
                expanded.append(u)

        website_texts: list[str] = []
        site_posts: list[dict] = []
        work_gallery: list[dict] = []
        producthunt_user = next(filter(None, map(site_scraper.producthunt_maker, expanded)), None)
        x_texts: list[str] = []
        linkedin_texts: list[str] = []
        x_stats_data: dict | None = None
        linkedin_stats_data: dict | None = None

        linkedin_url_used: str | None = None
        x_url_used: str | None = None
        if expanded:
            results = await asyncio.gather(*[_fetch_source(job_id, u) for u in expanded])
            for (orig_url, (kind, text, stats)) in zip(expanded, results):
                if not text:
                    if (stats or {}).get("link_only"):
                        link_only_urls.append(orig_url)
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
                    site_posts += (stats or {}).get("posts_raw") or []
                    work_gallery += (stats or {}).get("gallery") or []

        # Exclude resume — user-uploaded private document; public scrapes only
        scrape_raw: dict = {
            "github": github_data,
            "linkedin": "\n\n".join(linkedin_texts) or None,
            "x": "\n\n".join(x_texts) or None,
            "website": "\n\n".join(website_texts) or None,
        }

        if not any([github_data, resume_text, *website_texts, *x_texts, *linkedin_texts]):
            set_error(job_id, "None of these sources could be read. Use a public profile URL or upload a résumé, then retry.")
            return

        # A started model call can't be taken back (it runs in a thread and bills),
        # so a build the page has already replaced stops here.
        job = get_job(job_id)
        if job is None or job.cancelled:
            set_cancelled(job_id)
            return
        set_stage(job_id, "synthesizing")
        synth = await asyncio.to_thread(synthesize_card,
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
        # Nothing is read from a Product Hunt profile yet (launches are a follow-up), so the
        # link is what the person gets from it, whether or not the page could be read.
        if producthunt_user:
            synth.identity.links["producthunt"] = f"https://www.producthunt.com/@{producthunt_user}"
        for u in link_only_urls:
            synth.identity.links.setdefault(_link_key(u), _profile_link(u))

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
            synth.writing_samples, x_posts_raw, li_posts_raw, site_posts=site_posts,
        )

        card = cards_service.assemble_card(
            synth, github_data, github_handle, x_handle, bool(resume_text),
            linkedin_scraped=bool(linkedin_texts),
            x_stats=x_stats_data,
            linkedin_stats=linkedin_stats_data,
            contribution_stats=github_data.get("contribution_stats") if github_data else None,
            work_experience=work_experience_raw or None,
            x_scraped=bool(x_texts),
            work_gallery=work_gallery[: site_scraper.GALLERY_ITEMS],
        )

        # Set handles before set_ready so publish sees them immediately
        job = get_job(job_id)
        if job:
            job.handle_github = github_handle
            job.handle_x = x_handle
            job.linkedin_url = linkedin_url_used
        set_ready(job_id, card, scrape_raw=scrape_raw, persona=synth.persona)
    except Exception as exc:
        logger.warning("onboarding pipeline failed job=%s type=%s", job_id, type(exc).__name__)
        set_error(job_id, "We couldn't finish building your card. Your inputs are kept; please try again.")


@router.get("/claim-candidates")
async def claim_candidates(linkedin: str = Query("", max_length=500)):
    """S08 claim-first: published, unclaimed cards whose LinkedIn URL matches,
    so the UI can offer "claim it" instead of building a duplicate."""
    from services import cards as cards_service

    candidates = await asyncio.to_thread(cards_service.claim_candidates_by_linkedin, linkedin)
    return {"candidates": candidates}


@router.post("/start")
async def start_onboard(
    request: Request,
    url: list[str] = Form(default=[]),
    resume: UploadFile | None = File(None),
    source: str | None = Form(default=None),
    ref: str | None = Form(default=None),
    utm: str | None = Form(default=None),
):
    from services import events as events_service

    if _start_rate_limited(events_service.client_ip(request) or "anon"):
        raise HTTPException(status_code=429, detail="Too many card builds from this network. Wait a few minutes and try again.")

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
    get_job(job_id).task = asyncio.create_task(_run_pipeline(job_id, list(url), resume_text))

    start_meta: dict = {}
    if clean_source := events_service.sanitize_source(source):
        start_meta["source"] = clean_source
    if clean_utm := events_service.sanitize_utm(utm):
        start_meta["utm"] = clean_utm
    events_service.emit(
        "create_start",
        request=request,
        ref=ref,
        meta=start_meta or None,
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
        "url_warnings": job.url_warnings,
        "stage": job.stage,
        "sources": list(job.sources.values()),
        "persona": job.persona,
    }


@router.post("/{job_id}/cancel")
async def cancel_onboard(job_id: str):
    """The page started a newer build (a source was added or fixed): stop paying for this one."""
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return {"cancelled": cancel_job(job_id)}


@router.post("/{job_id}/publish")
async def publish_card(
    job_id: str,
    body: PublishRequest,
    request: Request,
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
        body.source,
        body.ref,
        body.utm,
        body.created_via or "web",
    )
    card.handle = handle  # frontend reads published.handle for redirect
    await hooks.run_publish_hooks(card.id, handle)
    from services import events as events_service

    events_service.emit(
        "create_publish",
        handle=handle,
        request=request,
        ref=body.ref,
        meta={"created_via": body.created_via or "web"},
    )
    result = card.model_dump(mode="json")
    if claim_token:
        result["claim_token"] = claim_token  # shown once; send as X-Claim-Token to claim
    return result
