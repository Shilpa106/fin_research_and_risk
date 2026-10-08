import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ...observability.context import (
    clear_observability_context,
    format_w3c_traceparent,
    generate_span_id,
    generate_trace_id,
    parse_w3c_traceparent,
    set_observability_context,
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Enterprise Context Propagation Middleware.
    Extracts or generates:
    - request_id / correlation_id
    - trace_id (via W3C traceparent or X-Trace-ID)
    - tenant_id
    - user_id
    - conversation_id
    - agent_run_id
    Binds the context to async Task contextvars and attaches W3C TraceContext headers to responses.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 1. Request ID / Correlation ID
        req_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or str(uuid.uuid4())
        )

        # 2. Distributed Trace ID & W3C TraceParent
        traceparent = request.headers.get("traceparent")
        parsed_trace = parse_w3c_traceparent(traceparent)
        if parsed_trace:
            trace_id, parent_span_id, _ = parsed_trace
        else:
            trace_id = request.headers.get("X-Trace-ID") or generate_trace_id()
            parent_span_id = None

        active_span_id = generate_span_id()

        # 3. Tenant, User, Conversation, Agent Lineage
        tenant_id = request.headers.get("X-Tenant-ID")
        user_id = request.headers.get("X-User-ID")
        conversation_id = request.headers.get("X-Conversation-ID")
        agent_run_id = request.headers.get("X-Agent-Run-ID")

        # 4. Bind to Task ContextVars
        set_observability_context(
            request_id=req_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            span_id=active_span_id,
        )

        # 5. Store on request.state for downstream route access
        request.state.request_id = req_id
        request.state.correlation_id = req_id
        request.state.trace_id = trace_id
        request.state.tenant_id = tenant_id
        request.state.user_id = user_id
        request.state.conversation_id = conversation_id
        request.state.agent_run_id = agent_run_id
        request.state.span_id = active_span_id

        try:
            response = await call_next(request)
            # Propagate lineage headers on outgoing response
            response.headers["X-Correlation-ID"] = req_id
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Trace-ID"] = trace_id
            response.headers["traceparent"] = format_w3c_traceparent(trace_id, active_span_id)
            return response
        finally:
            clear_observability_context()
