import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

os.environ.setdefault("ENVIRONMENT", "test")

from munych_api.config import Settings
from munych_api.main import create_app
from munych_api.shared.auth import get_token_verifier
from tests.support.auth import make_test_verifier
from tests.support.supabase import FakeRevalidator, FakeSupabase

# BD de las pruebas de integración: por defecto, el stack local de `supabase start`.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
)


async def _database_available(url: str) -> bool:
    import asyncpg

    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=3)
    except Exception:
        return False
    try:
        return bool(await conn.fetchval("select to_regclass('app.events') is not null"))
    finally:
        await conn.close()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    integration = [item for item in items if item.get_closest_marker("integration")]
    if not integration or asyncio.run(_database_available(TEST_DATABASE_URL)):
        return
    skip = pytest.mark.skip(
        reason="BD de integración no disponible: ejecuta `just db-start` y `just db-reset`"
    )
    for item in integration:
        item.add_marker(skip)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url=TEST_DATABASE_URL,
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
def fake_supabase(engine: AsyncEngine) -> FakeSupabase:
    return FakeSupabase(engine)


@pytest.fixture
def fake_revalidator() -> FakeRevalidator:
    return FakeRevalidator()


@pytest.fixture
async def app(
    settings: Settings, fake_supabase: FakeSupabase, fake_revalidator: FakeRevalidator
) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    application.dependency_overrides[get_token_verifier] = make_test_verifier
    application.state.supabase = fake_supabase
    application.state.revalidator = fake_revalidator
    yield application
    await application.state.database.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
