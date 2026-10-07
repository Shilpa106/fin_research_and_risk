import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from ....application.dtos import HealthComponentStatus, HealthResponse, LivenessResponse, ReadinessResponse
from ....config import get_settings
from ....infrastructure.database import check_db_health
from ....infrastructure.redis import check_redis_health

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health & Probes"])


@router.get("/health", response_model=HealthResponse, summary="General System Health")
async def get_health():
    """Returns application runtime metadata and environment status."""
    settings = get_settings()
    return HealthResponse(status="ok", version=settings.app_version, environment=settings.app_env)


@router.get("/health/live", response_model=LivenessResponse, summary="Kubernetes / ECS Liveness Probe")
async def get_liveness():
    """Liveness probe. Returns 200 OK as long as the process is alive."""
    return LivenessResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse, summary="Kubernetes / ECS Readiness Probe")
async def get_readiness():
    """
    Readiness probe for ALB/K8s ingress.
    Verifies live connectivity to PostgreSQL database and Redis cluster.
    """
    db_healthy = await check_db_health()
    redis_healthy = await check_redis_health()

    overall_ready = db_healthy and redis_healthy
    status_code = status.HTTP_200_OK if overall_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = ReadinessResponse(
        status="ready" if overall_ready else "not_ready",
        database=HealthComponentStatus(
            status="healthy" if db_healthy else "unhealthy",
            details="Database ping succeeded" if db_healthy else "Database connection failed",
        ),
        redis=HealthComponentStatus(
            status="healthy" if redis_healthy else "unhealthy",
            details="Redis ping succeeded" if redis_healthy else "Redis connection failed",
        ),
    )

    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
