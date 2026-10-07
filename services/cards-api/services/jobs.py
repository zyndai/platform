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
        job.card = card
        job.scrape_raw = scrape_raw


def set_error(job_id: str, message: str) -> None:
    if job := _jobs.get(job_id):
        job.status = "error"
        job.error = message
