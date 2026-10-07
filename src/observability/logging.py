import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any

# Context variables for distributed tracing correlation
correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)
tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """
    Formats log records as structured JSON with correlation IDs,
    service metadata, and ISO-8601 timestamps for OpenTelemetry/CloudWatch ingestion.
    """

    def __init__(self, service_name: str = "financial-research-copilot"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_ctx.get(),
            "tenant_id": tenant_id_ctx.get(),
            "user_id": user_id_ctx.get(),
            "caller": f"{record.filename}:{record.lineno}",
        }

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_payload.update(record.extra_fields)

        return json.dumps(log_payload)


def setup_logging(log_level: str = "INFO", service_name: str = "financial-research-copilot") -> logging.Logger:
    """Configures root logger with JSON formatting and stdout handler."""
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter(service_name=service_name))
    root_logger.addHandler(handler)

    return root_logger


def set_correlation_context(correlation_id: str, tenant_id: str | None = None, user_id: str | None = None) -> None:
    correlation_id_ctx.set(correlation_id)
    if tenant_id:
        tenant_id_ctx.set(tenant_id)
    if user_id:
        user_id_ctx.set(user_id)


def clear_correlation_context() -> None:
    correlation_id_ctx.set(None)
    tenant_id_ctx.set(None)
    user_id_ctx.set(None)
