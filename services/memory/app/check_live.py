"""Verify real embedding + extraction APIs work with the keys in .env.

    uv run python -m app.check_live     # or: make check

Requires MOCK_LLM=false and OPENAI_API_KEY (+ optional DEEPSEEK_API_KEY).
Costs a fraction of a cent. Run this before a full live ingest.
"""
import asyncio

from app.config import settings
from app.services.embeddings import embed
from app.services.extraction import extract_assertions

_SAMPLE = ("I am building an ML engineer marketplace for India and learning Rust "
           "async runtimes. I intend to raise a seed round this year.")


async def main() -> None:
    if settings.mock_llm:
        raise SystemExit("MOCK_LLM is true — set MOCK_LLM=false in .env to test live APIs.")

    vector = await embed("Rust async runtimes")
    print(f"embedding OK  — dim={len(vector)}  sample={[round(x, 4) for x in vector[:3]]}")

    assertions = await extract_assertions(_SAMPLE)
    print(f"extraction OK — {len(assertions)} assertions:")
    for a in assertions:
        print(f"  {a.predicate:18s} -> {a.object_name!r}  [{a.object_type}]  conf={a.confidence}")


if __name__ == "__main__":
    asyncio.run(main())
