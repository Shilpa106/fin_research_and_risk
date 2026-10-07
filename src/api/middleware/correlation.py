import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ...observability.logging import clear_correlation_context, set_correlation_context


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Extracts or generates W3C / X-Correlation-ID and X-Request-ID.
    Binds the correlation context to the async task contextvars.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = (
            request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())
        )
        tenant_id = request.headers.get("X-Tenant-ID")

        set_correlation_context(correlation_id=correlation_id, tenant_id=tenant_id)
        # Store on request.state for convenient route access
        request.state.correlation_id = correlation_id
        request.state.tenant_id = tenant_id

        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            clear_correlation_context()
