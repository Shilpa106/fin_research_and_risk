import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ...observability.context import get_observability_context
from ...observability.metrics import metrics_registry
from ...observability.tracing import SpanKind, default_tracer

logger = logging.getLogger("api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Enterprise Structured Access Logging & OpenTelemetry Instrumentation Middleware.
    Tracks API Golden Signals: RPS, p50, p95, p99 latency, and error rates.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        metrics_registry.http_active_requests_gauge.inc(1.0)
        ctx = get_observability_context()

        span_name = f"HTTP {request.method} {request.url.path}"
        with default_tracer.start_as_current_span(
            name=span_name,
            kind=SpanKind.SERVER,
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "http.target": request.url.path,
                "tenant.id": ctx.tenant_id,
                "request.id": ctx.request_id,
            },
        ) as span:
            try:
                response = await call_next(request)
                duration = time.time() - start_time

                # Record API golden signals
                metrics_registry.record_api_request(
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    duration_seconds=duration,
                    tenant_id=ctx.tenant_id,
                )

                span.set_attribute("http.status_code", response.status_code)

                # Log non-health requests
                if not request.url.path.startswith("/health"):
                    logger.info(
                        f"{request.method} {request.url.path} -> {response.status_code} "
                        f"({duration * 1000.0:.1f}ms) [tenant={ctx.tenant_id or 'none'}, req_id={ctx.request_id}]"
                    )

                return response
            except Exception as exc:
                duration = time.time() - start_time
                metrics_registry.record_api_request(
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=500,
                    duration_seconds=duration,
                    tenant_id=ctx.tenant_id,
                )
                span.record_exception(exc)
                span.set_attribute("http.status_code", 500)
                raise
            finally:
                metrics_registry.http_active_requests_gauge.dec(1.0)
