import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configure test environment variables prior to importing application modules
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

from src.api.main import create_app
from src.config.settings import AppSettings, get_settings
from src.domain.entities import Base, Tenant, TenantTier
from src.infrastructure.database import get_db_session


@pytest.fixture(scope="session")
def test_settings() -> AppSettings:
    """Returns application test settings."""
    return get_settings()


@pytest_asyncio.fixture
async def async_test_engine():
    """Async engine backed by in-memory SQLite for test isolation."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_db_session(async_test_engine) -> AsyncSession:
    """Provides isolated async database session with automatic transaction rollback."""
    session_factory = async_sessionmaker(
        bind=async_test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def sample_tenant(async_db_session: AsyncSession) -> Tenant:
    """Creates a sample enterprise tenant for testing."""
    tenant = Tenant(
        name="Morgan Stanley Asset Management",
        slug="msam",
        tier=TenantTier.ENTERPRISE,
        max_rate_limit_rps=5000,
        hitl_threshold_var=0.05,
    )
    async_db_session.add(tenant)
    await async_db_session.commit()
    await async_db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def test_client(async_db_session: AsyncSession):
    """Provides async HTTP client configured against the FastAPI app."""
    app = create_app()

    # Override get_db_session dependency with test session
    async def override_get_db_session():
        yield async_db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
