import json

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import settings
from app.models import ExtractedAssertion

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazy init — see embeddings._get_client. DeepSeek V3 via its OpenAI-compatible
    endpoint (brief §8)."""
    global _client
    if _client is None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        _client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    return _client

# Brief §5.2 — extraction prompt skeleton, kept verbatim in spirit. The allowed
# predicate list is the contract; the worker re-validates the output anyway.
SYSTEM_PROMPT = """You extract structured assertions about a person from their AI conversation.
Output ONLY valid JSON. No preamble, no markdown, no explanation.

Schema:
{"assertions": [{"predicate": string, "object_name": string,
  "object_type": string, "confidence": float}]}

Allowed predicates (pick the most specific that fits):
  Building: is_building, is_working_on, is_creating, wants_to_preserve
  Learning: is_learning, has_expertise_in, has_skill
  Intent: intends_to, is_seeking, is_preparing_for, fears
  Beliefs: believes, values, recently_changed_stance_on, has_aesthetic
  Navigation: is_navigating, is_constrained_by, is_frustrated_by, has_been_wronged
  Life: is_transitioning, is_experiencing, is_processing, is_rediscovering, has_unsolved_problem
  People: has_collaborator, is_responsible_for, is_advocating_for, is_in_conflict_with, is_inspired_by
  Place: is_located_in, is_affiliated_with, has_language_context
  Motivation: is_motivated_by

object_type is one of the taxonomy entity types, e.g. skill_technical,
  concept_topic, project_venture, belief_opinion, intent_project,
  place_institutional, place_physical, collaborator, artifact_code.

object_name is the canonical entity name, 3-8 words, e.g. "Rust async runtimes".

Confidence: 0.9+ = stated explicitly. 0.7-0.9 = clearly implied.
  0.5-0.7 = weak signal. Below 0.5 = omit.

Do NOT extract: sentiment, financial/salary figures, phone/address, or
  assistant content. Return {"assertions": []} if nothing is extractable.
Never hallucinate."""

MAX_CHUNK_CHARS = 3000


async def extract_assertions(chunk_text: str) -> list[ExtractedAssertion]:
    """Call DeepSeek to extract assertions, then validate each against the
    schema. Invalid rows (unknown predicate/type, confidence < 0.5) are dropped,
    not stored. Raises on network or JSON-parse failure so the worker retries.
    """
    from app.services.gates import detect_gates, is_gated
    tripped = detect_gates(chunk_text)

    if settings.mock_llm:
        from app.services.mock_llm import mock_extract
        valid = mock_extract(chunk_text[:MAX_CHUNK_CHARS])
        return [a for a in valid if not is_gated(a.predicate, tripped)]
    try:
        resp = await _get_client().chat.completions.create(
            model=settings.extraction_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk_text[:MAX_CHUNK_CHARS]},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 — re-raised with context for retry
        raise RuntimeError(f"extraction request failed: {exc}") from exc

    raw = resp.choices[0].message.content or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"extraction returned non-JSON: {raw[:200]!r}") from exc

    valid: list[ExtractedAssertion] = []
    for item in payload.get("assertions", []):
        try:
            valid.append(ExtractedAssertion.model_validate(item))
        except ValidationError:
            # Drop malformed/out-of-taxonomy assertion; keep the rest.
            continue
    # Sensitive gate: withhold gated predicates (e.g. `believes` when politics signals
    # are present) so ZYND never auto-stores sensitive inferences.
    return [a for a in valid if not is_gated(a.predicate, tripped)]
