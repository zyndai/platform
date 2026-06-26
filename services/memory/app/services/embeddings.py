from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None

# text-embedding-3-small accepts ~8191 tokens. Cap input chars well under that so an
# oversized chunk can't exceed the limit and create a permanently-failing worker job.
# The full raw_text is still stored in trace_chunks; only the embedding input is bounded.
EMBED_MAX_CHARS = 8000


def _get_client() -> AsyncOpenAI:
    """Lazy init so importing the app (and the LLM-free /ingest path) works
    without an API key; only actual embedding calls require one."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def embed(text: str) -> list[float]:
    """Return the 1536-dim embedding for `text` (text-embedding-3-small, brief §8).

    Raises on API/network failure so the caller (worker) can retry — we never
    want to silently store a missing or zero embedding.
    """
    cleaned = text.replace("\n", " ").strip()[:EMBED_MAX_CHARS]
    if not cleaned:
        raise ValueError("cannot embed empty text")
    if settings.mock_llm:
        from app.services.mock_llm import mock_embed
        return mock_embed(cleaned)
    try:
        resp = await _get_client().embeddings.create(model=settings.embedding_model, input=cleaned)
    except Exception as exc:  # noqa: BLE001 — re-raised with context, never swallowed
        raise RuntimeError(f"embedding request failed: {exc}") from exc
    return resp.data[0].embedding
