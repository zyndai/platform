from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if value is None:
        return ""
    return value


def _coerce_experience(v):
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize_booking_url(v) -> str | None:
    """Booking links render as a public <a href>: add a missing https:// (people
    paste "calendly.com/me"), and drop anything that still isn't an http(s) URL."""
    if not isinstance(v, str) or not v.strip():
        return None
    url = v.strip()
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else None


def _coerce_industries(v):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(v, list):
        return [x for x in v if x]
    return []


class Identity(BaseModel):
    name: str = ""
    headline: str = ""
    location: str = ""
    avatar_url: str = ""
    avatar_bg_url: str = ""
    links: dict[str, str] = Field(default_factory=dict)


class Skill(BaseModel):
    name: str
    level: str = "intermediate"
    evidence_count: int = 0

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_level(cls, v):
        return v or "intermediate"

    @field_validator("evidence_count", mode="before")
    @classmethod
    def _coerce_count(cls, v):
        if v in (None, ""):
            return 0
        return v


class Project(BaseModel):
    name: str = ""
    description: str = ""
    url: str = ""
    source: str = "github"
    stars: int | None = None
    tech: list[str] = Field(default_factory=list)

    @field_validator("stars", mode="before")
    @classmethod
    def _coerce_stars(cls, v):
        if v in (None, ""):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @field_validator("tech", mode="before")
    @classmethod
    def _coerce_tech(cls, v):
        if isinstance(v, str):
            return []
        return v


class WritingSample(BaseModel):
    platform: str = "x"
    excerpt: str = ""
    url: str = ""
    posted_at: str = ""
    metrics: list[str] = Field(default_factory=list)

    @field_validator("metrics", mode="before")
    @classmethod
    def _coerce_metrics(cls, v):
        if isinstance(v, str):
            return []
        return v


class Source(BaseModel):
    platform: str
    url: str | None = None
    scraped_at: str = ""
    method: str = ""


class Review(BaseModel):
    status: str = "pending_review"
    reviewed_by: str = "user_self"
    reviewed_at: str = ""


class AgentProfileCard(BaseModel):
    id: str
    schema_version: str = "1.0"
    status: str = "draft"
    handle: str = ""
    created_at: str = ""
    updated_at: str = ""
    identity: Identity = Field(default_factory=Identity)
    citation_snippet: str = ""
    summary: str = ""
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    writing_samples: list[WritingSample] = Field(default_factory=list)
    searchable_facts: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    review: Review = Field(default_factory=Review)
    experience_years: int | None = None
    industries: list[str] = Field(default_factory=list)
    availability: str = ""
    working_on: list[str] = Field(default_factory=list)
    can_help_with: list[str] = Field(default_factory=list)
    connect_with: list[str] = Field(default_factory=list)
    love_talking_about: list[str] = Field(default_factory=list)
    github_stats: dict = Field(default_factory=dict)
    affiliations: str = ""
    linkedin_stats: dict | None = None
    x_stats: dict | None = None
    contribution_stats: dict | None = None
    calendly_url: str | None = None
    # Google Calendar appointment-schedule booking page (calendar.app.google/…
    # or calendar.google.com/calendar/appointments/…). Separate from
    # calendly_url so agents reading the card never see a mislabelled link.
    google_calendar_url: str | None = None
    # Structured LinkedIn work experience entries extracted at scrape time.
    # Each entry: {title, company, company_logo, employment_type, start_date,
    #              end_date, duration, location, description}
    work_experience: list[dict] | None = None
    # Public findability facts pulled from the ZYND memory layer by our cron
    # (services/zynd_memory). None = not connected / nothing public yet.
    zynd_memory: list[dict] | None = None

    @field_validator("experience_years", mode="before")
    @classmethod
    def _coerce_experience_card(cls, v):
        return _coerce_experience(v)

    @field_validator("industries", mode="before")
    @classmethod
    def _coerce_industries_card(cls, v):
        return _coerce_industries(v)

    @field_validator("calendly_url", "google_calendar_url", mode="before")
    @classmethod
    def _normalize_booking_urls(cls, v):
        return normalize_booking_url(v)


class CardSynthesis(BaseModel):
    """The subset the LLM produces; id/status/timestamps are assembled server-side."""

    identity: Identity = Field(default_factory=Identity)
    citation_snippet: str = ""
    summary: str = ""
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    writing_samples: list[WritingSample] = Field(default_factory=list)
    searchable_facts: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    experience_years: int | None = None
    industries: list[str] = Field(default_factory=list)
    availability: str = ""
    working_on: list[str] = Field(default_factory=list)
    can_help_with: list[str] = Field(default_factory=list)
    connect_with: list[str] = Field(default_factory=list)
    love_talking_about: list[str] = Field(default_factory=list)
    github_stats: dict = Field(default_factory=dict)
    affiliations: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls(cls, data):
        cleaned = _clean(data)
        # _clean converts None→"" globally, but list fields reject "".
        # Convert any string-ified list field back to empty list.
        _LIST_KEYS = frozenset({
            "skills", "projects", "writing_samples", "searchable_facts",
            "sources", "working_on", "can_help_with", "connect_with",
            "love_talking_about",
        })
        for key in _LIST_KEYS:
            if isinstance(cleaned.get(key), str):
                cleaned[key] = []
        return cleaned

    @field_validator("experience_years", mode="before")
    @classmethod
    def _coerce_experience_synth(cls, v):
        return _coerce_experience(v)

    @field_validator("industries", mode="before")
    @classmethod
    def _coerce_industries_synth(cls, v):
        return _coerce_industries(v)
