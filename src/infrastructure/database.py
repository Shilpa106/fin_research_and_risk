import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings
from ..domain.entities import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        # SQLite compatibility flags for tests
        if "sqlite" in settings.database_url:
            connect_args["check_same_thread"] = False
            _engine = create_async_engine(settings.database_url, echo=settings.db_echo, connect_args=connect_args)
        else:
            # PostgreSQL connection pool settings for 10K RPS production
            _engine = create_async_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_pre_ping=True,
                echo=settings.db_echo,
            )
        logger.info(f"Initialized database async engine for {settings.database_url.split('@')[-1]}")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding database session with automatic commit/rollback."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def set_tenant_rls_context(session: AsyncSession, tenant_id: str) -> None:
    """Sets PostgreSQL session variable to enforce Row-Level Security in kernel."""
    settings = get_settings()
    if "postgresql" in settings.database_url:
        await session.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})


async def check_db_health() -> bool:
    """Executes ping query to verify database liveness."""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


async def dispose_db_engine() -> None:
    """Gracefully flushes pool connections during application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        logger.info("Disposing database connection pool...")
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection pool disposed.")


async def init_db_schema() -> None:
    """Creates database tables for local/testing execution."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema initialized.")


async def execute_with_retry(
    coroutine_func,
    max_retries: int = 3,
    initial_delay: float = 0.05,
    backoff_factor: float = 2.0,
):
    """
    Executes a database operation with exponential backoff retry.
    Catches transient disconnections, deadlocks, and network failures.
    """
    import asyncio
    delay = initial_delay
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return await coroutine_func()
        except Exception as exc:
            last_exc = exc
            if attempt == max_retries:
                logger.error(f"Database operation failed permanently after {max_retries} attempts: {exc}")
                raise exc
            logger.warning(f"Database operation failed (attempt {attempt}/{max_retries}): {exc}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay *= backoff_factor
    if last_exc:
        raise last_exc

