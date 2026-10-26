import asyncio
import secrets
from datetime import datetime, timezone

from models.card import AgentProfileCard

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


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
        self.task: asyncio.Task | None = None


_jobs: dict[str, _Job] = {}


def create_job() -> str:
    job_id = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    _jobs[job_id] = _Job()
    return job_id


def get_job(job_id: str) -> _Job | None:
    return _jobs.get(job_id)


def set_ready(job_id: str, card: AgentProfileCard, scrape_raw: dict | None = None) -> None:
    if job := _jobs.get(job_id):
        job.status = "ready"
        job.stage = "ready"
        job.card = card
        job.scrape_raw = scrape_raw


def set_error(job_id: str, message: str) -> None:
    if job := _jobs.get(job_id):
        job.status = "error"
        job.stage = "error"
        job.error = message


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
        job.task.cancel()
        return True
    return False
