import json
import re

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import settings
from app.models import ExtractedAssertion
from app.services.canonical import tech_kind

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
  Learning: is_learning, has_expertise_in, has_skill, uses_tool
  Intent: intends_to, is_seeking, is_preparing_for, fears
  Beliefs: believes, values, recently_changed_stance_on, has_aesthetic
  Navigation: is_navigating, is_constrained_by, is_frustrated_by, has_been_wronged
  Life: has_age, is_transitioning, is_experiencing, is_processing, is_rediscovering, has_unsolved_problem
  People: has_collaborator, is_responsible_for, is_advocating_for, is_in_conflict_with, is_inspired_by
  Place: is_located_in, is_affiliated_with, has_language_context
  Motivation: is_motivated_by

Choosing between building, working on, tools and expertise:
  is_building = a named venture, product or mission the person is creating
    (e.g. "Verusa"). Never a tool they use or a process they follow.
  is_working_on = a current work stream or process (e.g. "LinkedIn outreach",
    "AI-assisted delivery"). Short-lived.
  uses_tool = a product or tool the person operates but did not build
    (e.g. "Codex", "Claude Code", "Postgres"). A tool is never is_building and
    never has_expertise_in unless the person says they are an expert in it.
  has_expertise_in = a field the person has depth in, stated or clearly shown.
    A single mention is not expertise.

object_type is one of the taxonomy entity types, e.g. skill_technical,
  concept_topic, project_venture, belief_opinion, intent_project,
  place_institutional, place_physical, collaborator, artifact_code.

object_name is the canonical entity name, 3-8 words, e.g. "Rust async runtimes".

Confidence: 0.9+ = stated explicitly. 0.7-0.9 = clearly implied.
  0.5-0.7 = weak signal. Below 0.5 = omit.

Do NOT extract: sentiment, financial/salary figures, phone/address, or
  assistant content. Return {"assertions": []} if nothing is extractable.
Never hallucinate."""

# Added to the prompt when feature_strict_tech is on. Without it the model read "my build
# fails in some-lib's webpack config" as uses_tool -> webpack, and a pasted lockfile as a stack.
STRICT_BLOCK = """

What is NOT about the person (do not extract it):
  - A library, package or dependency that only appears inside an error message, a stack
    trace, a lockfile, a package.json/requirements file, a diff, or someone else's code.
  - A technology that is merely present in a project or mentioned in passing. uses_tool,
    has_skill and has_expertise_in need the person to say they use, know or write it.
  - A one-off task ("fix this bug", "rename this file", "bump the version"). is_working_on
    is for a work stream that lasts days or weeks, never for a single task.

Examples (input -> output):
  "my build fails in some-lib's webpack config"            -> {"assertions": []}
  "ModuleNotFoundError: No module named 'requests'"        -> {"assertions": []}
  "package.json has react, lodash and moment"              -> {"assertions": []}
  "can you rename this file and fix the typo"              -> {"assertions": []}
  "this repo is built on Kubernetes"                       -> {"assertions": []}
  "I run all my services on Kubernetes"                    -> uses_tool: Kubernetes
  "I've been writing Rust for six years"                   -> has_skill: Rust"""

MAX_CHUNK_CHARS = 3000

# Text that is machine output rather than the person speaking: a model that names tools found
# in it is describing the project, not the user.
_MACHINE_OUTPUT = re.compile(
    r"Traceback \(most recent call last\)|^\s+at .+\(.+:\d+:\d+\)|npm ERR!|ModuleNotFoundError|"
    r"ImportError:|Cannot find module|node_modules/|site-packages/|\"(?:dev)?[dD]ependencies\"\s*:\s*\{|"
    r"^\s*[\w.-]+==[\d.]+\s*$|^\+\+\+ |^--- a/|^diff --git",
    re.MULTILINE,
)
_TECH_PREDICATES = frozenset({"has_skill", "uses_tool", "has_expertise_in", "is_learning"})
# "fix the login bug", "rename this file": a task, not a work stream.
_ONE_OFF_TASK = re.compile(
    r"^(?:fix(?:ing)?|debug(?:ging)?|rename|renaming|bump(?:ing)?|patch(?:ing)?|resolve|resolving|"
    r"update|updating|tweak(?:ing)?)\b", re.IGNORECASE)


def looks_like_machine_output(text: str) -> bool:
    return bool(_MACHINE_OUTPUT.search(text or ""))


def guard_extractions(chunk_text: str, assertions: list[ExtractedAssertion]) -> list[ExtractedAssertion]:
    """Deterministic backstop for the strict prompt: never trust a model to enforce a rule alone.

    Drops technology facts from a chunk that is an error, trace, lockfile or diff, and
    is_working_on facts that read as a single task.
    """
    machine = looks_like_machine_output(chunk_text)
    kept: list[ExtractedAssertion] = []
    for item in assertions:
        if machine and item.predicate in _TECH_PREDICATES and tech_kind(item.object_name) is not None:
            continue
        if item.predicate == "is_working_on" and _ONE_OFF_TASK.match(item.object_name.strip()):
            continue
        kept.append(item)
    return kept


def system_prompt() -> str:
    return SYSTEM_PROMPT + STRICT_BLOCK if settings.feature_strict_tech else SYSTEM_PROMPT


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
        if settings.feature_strict_tech:
            valid = guard_extractions(chunk_text, valid)
        return [a for a in valid if not is_gated(a.predicate, tripped)]
    try:
        resp = await _get_client().chat.completions.create(
            model=settings.extraction_model,
            messages=[
                {"role": "system", "content": system_prompt()},
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
    if settings.feature_strict_tech:
        valid = guard_extractions(chunk_text, valid)
    # Sensitive gate: withhold gated predicates (e.g. `believes` when politics signals
    # are present) so ZYND never auto-stores sensitive inferences.
    return [a for a in valid if not is_gated(a.predicate, tripped)]
