import json
import logging
import sys
import time
from typing import Any

from .context import (
    agent_run_id_ctx,
    clear_observability_context,
    conversation_id_ctx,
    correlation_id_ctx,
    get_observability_context,
    request_id_ctx,
    set_observability_context,
    span_id_ctx,
    tenant_id_ctx,
    trace_id_ctx,
    user_id_ctx,
)
from .sanitizer import sanitize_payload, sanitize_text


class StructuredJsonFormatter(logging.Formatter):
    """
    Enterprise Structured JSON Log Formatter.
    Injects full distributed lineage (request_id, trace_id, tenant_id, user_id, conversation_id, agent_run_id).
    Strictly scrubs credentials, secrets, and sensitive financial information before emitting.
    """

    def __init__(self, service_name: str = "financial-research-copilot"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_observability_context()

        # Sanitize message
        raw_message = record.getMessage()
        clean_message = sanitize_text(raw_message)

        log_payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": clean_message,
            # Core Request Lineage
            "request_id": ctx.request_id,
            "correlation_id": ctx.request_id,
            "trace_id": ctx.trace_id,
            "span_id": ctx.span_id,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "conversation_id": ctx.conversation_id,
            "agent_run_id": ctx.agent_run_id,
            "caller": f"{record.filename}:{record.lineno}",
        }

        if record.exc_info:
            exc_str = self.formatException(record.exc_info)
            log_payload["exception"] = sanitize_text(exc_str)

        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            clean_extras = sanitize_payload(record.extra_fields)
            log_payload.update(clean_extras)

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


def set_correlation_context(
    correlation_id: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    agent_run_id: str | None = None,
) -> None:
    """Sets correlation and tenant execution contextvars."""
    set_observability_context(
        request_id=correlation_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
    )


def clear_correlation_context() -> None:
    """Clears all correlation contextvars."""
    clear_observability_context()
