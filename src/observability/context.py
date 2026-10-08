import re
import secrets
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# Context variables for distributed tracing, multi-tenancy, and execution correlation
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id", default=None)
tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)
conversation_id_ctx: ContextVar[str | None] = ContextVar("conversation_id", default=None)
agent_run_id_ctx: ContextVar[str | None] = ContextVar("agent_run_id", default=None)
span_id_ctx: ContextVar[str | None] = ContextVar("span_id", default=None)

# Backward-compatibility alias
correlation_id_ctx = request_id_ctx

# W3C TraceContext traceparent regex: 00-{trace_id}-{parent_id}-{flags}
TRACEPARENT_REGEX = re.compile(r"^00-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-([0-9a-fA-F]{2})$")


def generate_trace_id() -> str:
    """Generates a 32-character hexadecimal W3C compliant trace ID."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generates a 16-character hexadecimal span ID."""
    return secrets.token_hex(8)


def parse_w3c_traceparent(traceparent: str | None) -> tuple[str, str, str] | None:
    """
    Parses a W3C traceparent header value.
    Format: 00-{version_format}-{trace_id}-{parent_id}-{flags}
    Returns (trace_id, parent_span_id, flags) or None if invalid.
    """
    if not traceparent:
        return None
    match = TRACEPARENT_REGEX.match(traceparent.strip())
    if match:
        trace_id, parent_id, flags = match.groups()
        return trace_id.lower(), parent_id.lower(), flags
    return None


def format_w3c_traceparent(trace_id: str, span_id: str, flags: str = "01") -> str:
    """Formats trace_id and span_id into canonical W3C traceparent header."""
    return f"00-{trace_id}-{span_id}-{flags}"


@dataclass
class ObservabilityContext:
    """
    Unified Observability Execution Context.
    Captures complete transaction lineage across Ingress, RAG, Multi-Agent, and LLM tiers.
    """
    request_id: str
    trace_id: str
    tenant_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    agent_run_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def correlation_id(self) -> str:
        """Alias correlation_id to request_id for backward compatibility."""
        return self.request_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.request_id,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "agent_run_id": self.agent_run_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
        }

    def to_w3c_header(self) -> str:
        active_span = self.span_id or generate_span_id()
        return format_w3c_traceparent(self.trace_id, active_span)


def set_observability_context(
    request_id: str | None = None,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    agent_run_id: str | None = None,
    span_id: str | None = None,
    correlation_id: str | None = None,
) -> ObservabilityContext:
    """
    Sets context variables for the current asynchronous execution context.
    Generates request_id, trace_id, and span_id if not provided.
    """
    req_id = request_id or correlation_id or str(uuid.uuid4())
    t_id = trace_id or generate_trace_id()
    s_id = span_id or generate_span_id()

    request_id_ctx.set(req_id)
    trace_id_ctx.set(t_id)
    span_id_ctx.set(s_id)
    tenant_id_ctx.set(tenant_id)
    user_id_ctx.set(user_id)
    conversation_id_ctx.set(conversation_id)
    agent_run_id_ctx.set(agent_run_id)

    return ObservabilityContext(
        request_id=req_id,
        trace_id=t_id,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        span_id=s_id,
    )


def get_observability_context() -> ObservabilityContext:
    """Retrieves current observability execution context from contextvars."""
    req_id = request_id_ctx.get() or str(uuid.uuid4())
    t_id = trace_id_ctx.get() or generate_trace_id()
    s_id = span_id_ctx.get() or generate_span_id()

    return ObservabilityContext(
        request_id=req_id,
        trace_id=t_id,
        tenant_id=tenant_id_ctx.get(),
        user_id=user_id_ctx.get(),
        conversation_id=conversation_id_ctx.get(),
        agent_run_id=agent_run_id_ctx.get(),
        span_id=s_id,
    )


def clear_observability_context() -> None:
    """Clears all observability context variables."""
    request_id_ctx.set(None)
    trace_id_ctx.set(None)
    span_id_ctx.set(None)
    tenant_id_ctx.set(None)
    user_id_ctx.set(None)
    conversation_id_ctx.set(None)
    agent_run_id_ctx.set(None)
