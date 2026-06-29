from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.taxonomy import ENTITY_TYPES, INFERRABLE_PREDICATES


# ---- Inbound: what the ChatGPT plugin (or any source) POSTs to /ingest ----

class Turn(BaseModel):
    role: str
    content: str
    timestamp: datetime | None = None


class IngestRequest(BaseModel):
    conversation_id: str | None = None
    source_system: str = "chatgpt"
    turns: list[Turn]


class IngestResponse(BaseModel):
    status: str = "ok"
    chunks_inserted: int
    chunks_skipped: int


# ---- LLM extraction output. Validated before anything touches the DB ----
#      (brief §14.3: never write LLM output straight to the database).

class ExtractedAssertion(BaseModel):
    predicate: str
    object_name: str = Field(min_length=1, max_length=200)
    object_type: str
    confidence: float

    @field_validator("predicate")
    @classmethod
    def _known_predicate(cls, v: str) -> str:
        if v not in INFERRABLE_PREDICATES:  # system/declared-only predicates can't be extracted
            raise ValueError(f"unknown predicate: {v}")
        return v

    @field_validator("object_type")
    @classmethod
    def _known_entity_type(cls, v: str) -> str:
        if v not in ENTITY_TYPES:
            raise ValueError(f"unknown entity_type: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_floor(cls, v: float) -> float:
        # Brief §5.1: anything below 0.5 is omitted at extraction time.
        if v < 0.5:
            raise ValueError("confidence below 0.5 floor")
        return v


# ---- Outbound: GET /users/{id}/graph ----

class ContextRequest(BaseModel):
    topic: str = Field(min_length=1)
    k: int = Field(default=20, ge=1, le=50)


class FactRef(BaseModel):
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)


class DeclareRequest(BaseModel):
    predicate: str = Field(min_length=1)
    value: str = Field(min_length=1)


class AssertionView(BaseModel):
    statement: str = ""        # natural-language rendering for display (humanize)
    predicate: str
    object: str | None
    object_type: str | None
    confidence: float
    source_system: str
    decay_fn: str
    version: int
    observed_at: datetime | None
