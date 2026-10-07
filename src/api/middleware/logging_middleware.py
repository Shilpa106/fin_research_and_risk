import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ...observability.metrics import metrics_registry

logger = logging.getLogger("api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured access logging middleware recording request duration and status.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        metrics_registry.active_requests += 1

        try:
            response = await call_next(request)
            duration = time.time() - start_time
            metrics_registry.record_request(duration=duration, is_error=(response.status_code >= 500))

            # Exclude noisy high-frequency health probes from standard logs
            if not request.url.path.startswith("/health"):
                logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration * 1000:.1f}ms)")
            return response
        except Exception:
            duration = time.time() - start_time
            metrics_registry.record_request(duration=duration, is_error=True)
            raise
        finally:
            metrics_registry.active_requests -= 1
