import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from ...application.dtos import ErrorResponse
from ...domain.exceptions import BaseAppException
from ...observability.logging import correlation_id_ctx

logger = logging.getLogger(__name__)


async def app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    """Standardized handler for domain application exceptions."""
    correlation_id = getattr(request.state, "correlation_id", correlation_id_ctx.get())
    error_dto = ErrorResponse(
        error=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        correlation_id=correlation_id,
        details=exc.details,
    )
    logger.warning(
        f"Handled application exception: {exc.error_code} - {exc.message}",
        extra={"error_code": exc.error_code, "status_code": exc.status_code},
    )
    return JSONResponse(status_code=exc.status_code, content=error_dto.model_dump(mode="json"))


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler for unhandled 500 internal server errors."""
    correlation_id = getattr(request.state, "correlation_id", correlation_id_ctx.get())
    logger.exception(f"Unhandled server error: {str(exc)}")
    error_dto = ErrorResponse(
        error="INTERNAL_SERVER_ERROR",
        message="An unexpected internal server error occurred. Please contact institutional support.",
        status_code=500,
        correlation_id=correlation_id,
        details={"error_type": exc.__class__.__name__},
    )
    return JSONResponse(status_code=500, content=error_dto.model_dump(mode="json"))
