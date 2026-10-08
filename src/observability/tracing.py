import asyncio
import functools
import inspect
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .context import (
    ObservabilityContext,
    format_w3c_traceparent,
    generate_span_id,
    generate_trace_id,
    get_observability_context,
    parse_w3c_traceparent,
    set_observability_context,
    span_id_ctx,
    trace_id_ctx,
)
from .sanitizer import sanitize_payload

logger = logging.getLogger("enterprise_copilot.observability.tracing")


class SpanStatus(str, Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class SpanKind(str, Enum):
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


@dataclass
class SpanContext:
    """OpenTelemetry-compatible Span Context."""
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    trace_flags: str = "01"


@dataclass
class Span:
    """
    OpenTelemetry-compatible Distributed Trace Span.
    Represents a timed contiguous block of execution within an end-to-end request lifecycle.
    """
    name: str
    context: SpanContext
    kind: SpanKind = SpanKind.INTERNAL
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    duration_ms: float = 0.0
    status: SpanStatus = SpanStatus.UNSET
    status_description: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> "Span":
        """Sets a semantic attribute on the span with PII/secret scrubbing."""
        self.attributes[key] = sanitize_payload(value)
        return self

    def set_attributes(self, attrs: dict[str, Any]) -> "Span":
        """Sets multiple attributes on the span."""
        for k, v in attrs.items():
            self.set_attribute(k, v)
        return self

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> "Span":
        """Adds a timed event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": sanitize_payload(attributes or {}),
        })
        return self

    def record_exception(self, exception: Exception, escaped: bool = False) -> "Span":
        """Records an exception event and marks span status as ERROR."""
        self.status = SpanStatus.ERROR
        self.status_description = str(exception)
        self.add_event(
            name="exception",
            attributes={
                "exception.type": type(exception).__name__,
                "exception.message": str(exception),
                "exception.escaped": escaped,
            },
        )
        return self

    def set_status(self, status: SpanStatus, description: str | None = None) -> "Span":
        """Explicitly sets span completion status."""
        self.status = status
        self.status_description = description
        return self

    def end(self) -> None:
        """Finalizes span duration and registers with tracer buffer."""
        if self.end_time is None:
            self.end_time = time.time()
            self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 3)
            if self.status == SpanStatus.UNSET:
                self.status = SpanStatus.OK

    def to_dict(self) -> dict[str, Any]:
        """Serializes span to OpenTelemetry-compatible dictionary representation."""
        return {
            "name": self.name,
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_span_id": self.context.parent_span_id,
            "kind": self.kind.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": {
                "code": self.status.value,
                "description": self.status_description,
            },
            "attributes": self.attributes,
            "events": self.events,
        }


class Tracer:
    """
    OpenTelemetry-compatible In-Process Tracer.
    Manages active span stack, context propagation, and span lifecycle.
    """

    def __init__(self, service_name: str = "financial-research-copilot", max_buffer_size: int = 1000):
        self.service_name = service_name
        self.max_buffer_size = max_buffer_size
        self._finished_spans: list[Span] = []

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        parent_context: SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """Creates a new span within current or parent context."""
        ctx = get_observability_context()

        # Determine trace_id and parent_span_id
        if parent_context:
            trace_id = parent_context.trace_id
            parent_id = parent_context.span_id
        elif ctx.span_id:
            trace_id = ctx.trace_id
            parent_id = ctx.span_id
        else:
            trace_id = ctx.trace_id or generate_trace_id()
            parent_id = None

        span_id = generate_span_id()
        span_ctx = SpanContext(trace_id=trace_id, span_id=span_id, parent_span_id=parent_id)

        span = Span(
            name=name,
            context=span_ctx,
            kind=kind,
            attributes={
                "service.name": self.service_name,
                "tenant.id": ctx.tenant_id,
                "user.id": ctx.user_id,
                "conversation.id": ctx.conversation_id,
                "agent_run.id": ctx.agent_run_id,
                **(attributes or {}),
            },
        )
        return span

    def record_span(self, span: Span) -> None:
        """Appends finished span to in-memory buffer."""
        span.end()
        self._finished_spans.append(span)
        if len(self._finished_spans) > self.max_buffer_size:
            self._finished_spans.pop(0)

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ):
        """Context manager setting span as active in contextvars."""
        previous_span_id = span_id_ctx.get()
        previous_trace_id = trace_id_ctx.get()
        span = self.start_span(name=name, kind=kind, attributes=attributes)
        span_id_ctx.set(span.context.span_id)
        trace_id_ctx.set(span.context.trace_id)

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            self.record_span(span)
            span_id_ctx.set(previous_span_id)
            trace_id_ctx.set(previous_trace_id)

    def get_finished_spans(self) -> list[Span]:
        """Returns snapshot of completed spans."""
        return list(self._finished_spans)

    def clear(self) -> None:
        """Clears trace buffer."""
        self._finished_spans.clear()


# Global Singleton Tracer
default_tracer = Tracer()


def trace_span(
    name: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
    tracer: Tracer | None = None,
) -> Callable:
    """
    Decorator for tracing synchronous and asynchronous functions.
    Auto-instruments execution duration, parameters, and exceptions into a distributed span.
    """
    active_tracer = tracer or default_tracer

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with active_tracer.start_as_current_span(name=span_name, kind=kind, attributes=attributes) as span:
                    span.set_attribute("code.function", func.__name__)
                    return await func(*args, **kwargs)

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with active_tracer.start_as_current_span(name=span_name, kind=kind, attributes=attributes) as span:
                    span.set_attribute("code.function", func.__name__)
                    return func(*args, **kwargs)

            return sync_wrapper

    return decorator
