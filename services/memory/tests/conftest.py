"""Test fixtures.

Integration tests run against a dedicated `zynd_test` database (never the dev
DB) and use MOCK_LLM so no API keys or spend are involved. If Postgres is not
reachable, integration tests skip rather than fail — unit tests always run.

Env must be set BEFORE app modules import their cached settings, so it lives at
the top of conftest (pytest imports conftest before any test module).
"""
import os
import pathlib

os.environ["MOCK_LLM"] = "true"   # hermetic: ignore .env LLM settings
os.environ["DATABASE_URL"] = "postgresql://zynd:zynd@localhost:5433/zynd_test"
os.environ["ENABLE_DEV_BEARER"] = "true"   # tests authenticate with the dev token

import asyncpg
import httpx
import pytest
import pytest_asyncio

ADMIN_DSN = "postgresql://zynd:zynd@localhost:5433/zynd"
TEST_DSN = os.environ["DATABASE_URL"]
SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[1] / "sql" / "schema.sql"

_DERIVED_TABLES = "assertion_history, assertions, user_embeddings, entities, trace_chunks, published_pages"


async def _setup_test_db() -> None:
    admin = await asyncpg.connect(ADMIN_DSN, timeout=3)
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = 'zynd_test'")
        if not exists:
            await admin.execute("CREATE DATABASE zynd_test")
    finally:
        await admin.close()

    conn = await asyncpg.connect(TEST_DSN, timeout=3)
    try:
        await conn.execute(SCHEMA_PATH.read_text())  # idempotent
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def _test_db():
    try:
        await _setup_test_db()
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")
    yield


@pytest_asyncio.fixture
async def client(_test_db):
    """ASGI client with the app's real lifespan (DB pool, arq pool, dev user).
    Derived tables are truncated per test for isolation; users are kept so the
    lifespan-created dev user persists."""
    from app.db import get_pool
    from app.main import app

    async with app.router.lifespan_context(app):
        await get_pool().execute(f"TRUNCATE {_DERIVED_TABLES} RESTART IDENTITY CASCADE")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
