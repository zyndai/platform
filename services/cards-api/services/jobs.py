import asyncio
import secrets
import time
from datetime import datetime, timezone

from models.card import AgentProfileCard

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

# Jobs live in this process's memory, and every build holds its card and raw
# scrapes. A finished job is kept long enough for the person to review the draft
# and publish it, then dropped. A running one is never dropped: the pipeline's
# own timeout (api/onboard.py) ends it.
JOB_TTL_SECONDS = 2 * 60 * 60


def new_card_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Job:
    def __init__(self) -> None:
        self.status = "running"
        self.card: AgentProfileCard | None = None
        self.error: str | None = None
        self.handle_github: str | None = None
        self.handle_x: str | None = None
        self.linkedin_url: str | None = None
        self.scrape_raw: dict | None = None
        self.url_warnings: list[dict] = []
        # What the page shows while the build runs: one entry per source
        # (state + whatever that source has revealed so far) and the stage the
        # whole build is in. Keyed by URL; insertion order is display order.
        self.sources: dict[str, dict] = {}
        self.stage = "reading"
        # Which kind of professional the synthesis decided this is (synthesis/taxonomy.py); "" until ready.
        self.persona = ""
        self.task: asyncio.Task | None = None
        # Set by cancel_job, so the pipeline can skip the paid model call even
        # if it reaches it before the task's cancellation lands.
        self.cancelled = False
        self.created_at = time.monotonic()


_jobs: dict[str, _Job] = {}


def _evict_expired(now: float) -> None:
    for job_id, job in list(_jobs.items()):
        running = job.task is not None and not job.task.done()
        if not running and now - job.created_at > JOB_TTL_SECONDS:
            del _jobs[job_id]


def create_job() -> str:
    _evict_expired(time.monotonic())
    job_id = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    _jobs[job_id] = _Job()
    return job_id


def get_job(job_id: str) -> _Job | None:
    return _jobs.get(job_id)


def set_ready(job_id: str, card: AgentProfileCard, scrape_raw: dict | None = None, persona: str = "") -> None:
    if job := _jobs.get(job_id):
        job.status = "ready"
        job.stage = "ready"
        job.card = card
        job.scrape_raw = scrape_raw
        job.persona = persona


def set_error(job_id: str, message: str) -> None:
    if job := _jobs.get(job_id):
        job.status = "error"
        job.stage = "error"
        job.error = message


def set_cancelled(job_id: str) -> None:
    if job := _jobs.get(job_id):
        job.cancelled = True
        job.status = "cancelled"
        job.stage = "cancelled"


def set_source(job_id: str, url: str, kind: str, state: str, preview: dict | None = None) -> None:
    """Record where one source stands. `state` is reading | done | failed."""
    if job := _jobs.get(job_id):
        job.sources[url] = {"url": url, "kind": kind, "state": state, "preview": preview or {}}


def set_stage(job_id: str, stage: str) -> None:
    if job := _jobs.get(job_id):
        job.stage = stage


def cancel_job(job_id: str) -> bool:
    """Stop a build the page no longer wants (it started a newer one). True if a task was cancelled."""
    job = _jobs.get(job_id)
    if job and job.task and not job.task.done():
        job.cancelled = True
        job.task.cancel()
        return True
    return False
