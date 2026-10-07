import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings
from ..domain.exceptions import BaseAppException
from ..infrastructure.database import check_db_health, dispose_db_engine, init_db_schema
from ..infrastructure.redis import check_redis_health, close_redis_pool
from ..observability.logging import setup_logging
from .middleware.correlation import CorrelationIdMiddleware
from .middleware.error_handler import app_exception_handler, generic_exception_handler
from .middleware.logging_middleware import RequestLoggingMiddleware
from .v1.endpoints import health
from .v1.router import v1_router

logger = logging.getLogger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifespan Context Manager.
    Handles graceful resource initialization and disposal.
    """
    settings = get_settings()
    # 1. Initialize Structured Logging
    setup_logging(log_level=settings.log_level, service_name=settings.otel_service_name)
    logger.info(f"Starting {settings.app_name} [Env: {settings.app_env}, Version: {settings.app_version}]")

    # 2. Database schema initialization in non-production
    if settings.app_env in ["development", "test"]:
        try:
            await init_db_schema()
            logger.info("Local database schema checked and ready.")
        except Exception as e:
            logger.warning(f"Could not auto-initialize database schema: {e}")

    # 3. Connectivity checks
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    logger.info(
        f"Startup probes - Database: {'HEALTHY' if db_ok else 'UNHEALTHY'}, Redis: {'HEALTHY' if redis_ok else 'UNHEALTHY'}"
    )

    yield

    # 4. Graceful Shutdown
    logger.info("Initiating graceful shutdown sequence...")
    await dispose_db_engine()
    await close_redis_pool()
    logger.info("All connection pools disposed. Process exiting.")


def create_app() -> FastAPI:
    """
    FastAPI Application Factory.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Enterprise Financial Research & Risk Copilot API Gateway",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )

    # 1. Mount Core Middleware (Execution order: outer -> inner)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Register Global Exception Handlers
    app.add_exception_handler(BaseAppException, app_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # 3. Mount Ingress & Health Probes at Root Level
    app.include_router(health.router)

    # 4. Mount Versioned API Routes (/api/v1)
    app.include_router(v1_router, prefix=settings.api_prefix)

    return app


# Singleton app instance for uvicorn
app = create_app()
