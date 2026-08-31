import secrets
from datetime import datetime, timezone

from models.card import AgentProfileCard

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def new_card_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Job:
    def __init__(self, handle_github: str | None, handle_x: str | None):
        self.status = "running"
        self.card: AgentProfileCard | None = None
        self.error: str | None = None
        self.handle_github = handle_github
        self.handle_x = handle_x


_jobs: dict[str, _Job] = {}


def create_job(handle_github: str | None = None, handle_x: str | None = None) -> str:
    job_id = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    _jobs[job_id] = _Job(handle_github, handle_x)
    return job_id


def get_job(job_id: str) -> _Job | None:
    return _jobs.get(job_id)


def set_ready(job_id: str, card: AgentProfileCard) -> None:
    if job := _jobs.get(job_id):
        job.status = "ready"
        job.card = card


def set_error(job_id: str, message: str) -> None:
    if job := _jobs.get(job_id):
        job.status = "error"
        job.error = message
