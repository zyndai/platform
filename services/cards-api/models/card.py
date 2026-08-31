from pydantic import BaseModel, Field, field_validator, model_validator


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if value is None:
        return ""
    return value


class Identity(BaseModel):
    name: str = ""
    headline: str = ""
    location: str = ""
    avatar_url: str = ""
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


class WritingSample(BaseModel):
    platform: str = "x"
    excerpt: str = ""
    url: str = ""
    posted_at: str = ""


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls(cls, data):
        return _clean(data)
