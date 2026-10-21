from urllib.parse import urlparse
from datetime import datetime, timedelta

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_serializer, model_validator
from services.profile_quality import clean_topic, clean_topics


class TopicFields(BaseModel):
    @field_validator("skills", mode="before", check_fields=False)
    @classmethod
    def _valid_skills(cls, value):
        return clean_topics(value) if isinstance(value, list) else value

    @field_validator("can_help_with", "love_talking_about", mode="before", check_fields=False)
    @classmethod
    def _valid_topics(cls, value):
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(text for item in value if (text := clean_topic(item))))


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


EDITION_IDS = ("mumbai-26",)
EDITION_MOODS = ("night", "dusk", "monsoon")
EDITION_HERE_FOR = ("hacking", "speaking", "building", "hiring", "raising", "investing", "exploring")


class Edition(BaseModel):
    """A limited-edition look the owner picked for their card (cards-web renders it)."""

    id: Literal[EDITION_IDS]
    mood: Literal[EDITION_MOODS] = "night"
    here_for: Literal[EDITION_HERE_FOR] | None = None


class Identity(BaseModel):
    name: str = ""
    headline: str = ""
    location: str = ""
    avatar_url: str = ""
    avatar_bg_url: str = ""
    links: dict[str, str] = Field(default_factory=dict)
    # Lives in identity so the editor's existing identity section saves it:
    # cards.s10_save_section only accepts a fixed list of top-level keys.
    edition: Edition | None = None

    @field_validator("edition", mode="before")
    @classmethod
    def _known_edition_or_none(cls, v):
        # A stored edition that is no longer offered, or junk from an older
        # client, renders as the classic card instead of failing the whole read.
        if not isinstance(v, dict):
            return None
        try:
            return Edition.model_validate(v)
        except ValidationError:
            return None

    @model_serializer(mode="wrap")
    def _omit_missing_edition(self, handler):
        # Classic cards serialize (and are stored) exactly as before the edition
        # existed. Clearing an edition drops the key, since identity is saved whole.
        data = handler(self)
        if data.get("edition") is None:
            data.pop("edition", None)
        return data


class SkillEvidence(BaseModel):
    label: str = Field(default="Public source", max_length=200)
    url: str
    kind: str = "source"

    @field_validator("url")
    @classmethod
    def _public_link(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Evidence must be an http(s) URL without credentials")
        return value


class Skill(BaseModel):
    name: str
    level: str = "intermediate"
    evidence_count: int = 0
    evidence: list[SkillEvidence] = Field(default_factory=list, max_length=5)

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
    demo_url: str | None = None

    @field_validator("demo_url", mode="before")
    @classmethod
    def _demo_url(cls, value):
        return normalize_booking_url(value)

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


class Beacon(BaseModel):
    text: str = Field(min_length=1, max_length=280)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _seven_days(self):
        if not self.text.strip():
            raise ValueError("Beacon text is required")
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Beacon timestamps require a timezone")
        if not self.created_at < self.expires_at <= self.created_at + timedelta(days=7):
            raise ValueError("Beacons expire within seven days")
        return self


class CardFact(BaseModel):
    text: str = ""
    type: str = ""
    source: str = ""
    approved_at: str | None = None
    expires_at: str | None = None
    confidence: float | None = None


class CardView(TopicFields):
    """Canonical public card: identity + approved live memory facts."""

    handle: str = ""
    claimed: bool = False
    identity: Identity = Field(default_factory=Identity)
    summary: str = ""
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    working_on: list[str] = Field(default_factory=list)
    can_help_with: list[str] = Field(default_factory=list)
    love_talking_about: list[str] = Field(default_factory=list)
    availability: str = ""
    facts: list[CardFact] = Field(default_factory=list)
    cite_as: str = ""
    fresh_as_of: str | None = None
    calendly_url: str | None = None
    google_calendar_url: str | None = None
    links: dict[str, str] = Field(default_factory=dict)
    beacon: Beacon | None = None


class AgentProfileCard(TopicFields):
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
    # Public findability facts from the ZYND memory layer.
    # None = not connected. [] = connected, nothing public.
    zynd_memory: list[dict] | None = None
    # Handles this card used to live at (renames + collision-resuffixes).
    # Kept so old /p/<handle> links still resolve — get_card_by_handle falls
    # back to this list before 404ing.
    previous_handles: list[str] = Field(default_factory=list)
    beacon: Beacon | None = None

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


class CardSynthesis(TopicFields):
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
