"""Apply sql/schema.sql via asyncpg (no psql binary needed). Idempotent.

Used as the Render preDeployCommand and runnable locally:
    uv run python -m app.schema_apply
"""
import asyncio
import pathlib

from app.db import close_pool, get_pool, init_pool

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[1] / "sql" / "schema.sql"


async def main() -> None:
    await init_pool()
    try:
        await get_pool().execute(SCHEMA_PATH.read_text())
        print("schema applied")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
