import json

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Create the shared connection pool. Call once at process startup."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db pool not initialized; call init_pool() first")
    return _pool


def to_pgvector(vec: list[float]) -> str:
    """Serialize a float list to pgvector's text input form: "[0.1,0.2,...]".

    We bind it as a string and cast with ::vector in SQL, which avoids needing
    the optional pgvector codec registration.
    """
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def from_pgvector(text: str) -> list[float]:
    """Parse pgvector's text output ("[0.1,0.2,...]") back to a float list.
    The format is a JSON array, so json.loads handles it directly."""
    return [float(x) for x in json.loads(text)]
