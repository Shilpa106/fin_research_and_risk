import asyncio
import collections
import logging
import time
from typing import Any

from pydantic import ValidationError

from ..domain.exceptions import (
    RateLimitExceededException,
    ToolExecutionTimeoutException,
    ToolNotFoundException,
    ToolValidationException,
)
from .models import ToolDefinition, ToolResult, ToolSecurityContext
from .security import MCPSecurityValidator
from .servers.base import BaseMCPServer
from .servers.market_server import MarketDataServer
from .servers.portfolio_server import PortfolioServer
from .servers.research_server import ResearchServer

logger = logging.getLogger("enterprise_copilot.mcp.gateway")


class MCPGateway:
    """
    Centralized Model Context Protocol (MCP) Enterprise Tool Gateway.

    Governance & Perimeter Controls:
    - Tool discovery and typed schema introspection
    - Agent tool allowlist enforcement (agents NEVER have unrestricted API access)
    - Input & output schema validation via Pydantic
    - Multi-tenant boundary isolation
    - Defense against injection attacks (SQLi, shell injection, path traversal)
    - Timeout SLA enforcement
    - Multi-tenant rate limiting
    - Immutable security audit logging
    """

    def __init__(
        self,
        default_timeout_seconds: float = 10.0,
        default_rpm_limit: int = 300,
    ):
        self.default_timeout_seconds = default_timeout_seconds
        self.default_rpm_limit = default_rpm_limit

        self.servers: dict[str, BaseMCPServer] = {}
        self.tools: dict[str, tuple[ToolDefinition, BaseMCPServer]] = {}

        # Tenant rate limiting: tenant_id -> deque of timestamps
        self._rate_limits: collections.defaultdict[str, collections.deque[float]] = collections.defaultdict(collections.deque)
        self.tenant_rpm_overrides: dict[str, int] = {}

        # Audit logs storage
        self.audit_events: list[dict[str, Any]] = []

        # Auto-register default institutional servers
        self.register_server(MarketDataServer())
        self.register_server(ResearchServer())
        self.register_server(PortfolioServer())

    def register_server(self, server: BaseMCPServer) -> None:
        """Mounts an MCP server and indexes its tools."""
        self.servers[server.server_name] = server
        for tool_def in server.list_tools():
            self.tools[tool_def.name] = (tool_def, server)
        logger.info("Mounted MCP server '%s' with %d tools.", server.server_name, len(server.list_tools()))

    def list_tools(self, agent_type: str | None = None) -> list[ToolDefinition]:
        """
        Tool discovery endpoint.
        Filters available tools against agent allowlists if agent_type is specified.
        """
        available = []
        for tool_def, _ in self.tools.values():
            if agent_type:
                try:
                    MCPSecurityValidator.validate_allowlist(agent_type, tool_def.name)
                    available.append(tool_def)
                except Exception:
                    continue
            else:
                available.append(tool_def)
        return available

    def get_tool_definition(self, tool_name: str) -> ToolDefinition | None:
        """Retrieves schema definition for a tool."""
        entry = self.tools.get(tool_name)
        return entry[0] if entry else None

    def _check_rate_limit(self, tenant_id: str) -> None:
        """Sliding-window rate limiter per tenant."""
        now = time.time()
        window_start = now - 60.0
        limit = self.tenant_rpm_overrides.get(tenant_id, self.default_rpm_limit)

        q = self._rate_limits[tenant_id]
        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= limit:
            retry_after = max(1, int(60.0 - (now - q[0])))
            raise RateLimitExceededException(
                retry_after=retry_after,
                message=f"MCP Gateway rate limit exceeded for tenant '{tenant_id}' ({len(q)}/{limit} RPM).",
            )
        q.append(now)

    def _log_audit_event(
        self,
        tool_name: str,
        context: ToolSecurityContext,
        status: str,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Records immutable audit trail for governance compliance."""
        event = {
            "timestamp": time.time(),
            "request_id": context.request_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "agent_type": context.agent_type,
            "tool_name": tool_name,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "error": error,
        }
        self.audit_events.append(event)
        logger.info(
            "MCP Tool Audit | RequestID: %s | Tenant: %s | User: %s | Agent: %s | Tool: %s | Status: %s | Duration: %.2fms | Error: %s",
            context.request_id,
            context.tenant_id,
            context.user_id,
            context.agent_type,
            tool_name,
            status,
            duration_ms,
            error,
        )

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolSecurityContext,
        timeout_seconds: float | None = None,
    ) -> ToolResult:
        """
        Executes a secure, governed MCP tool call.

        Verification Pipeline:
        1. Tool existence check
        2. Agent allowlist validation
        3. RBAC & permission authorization
        4. Malicious input payload scan
        5. Tenant isolation boundary validation
        6. Input schema validation (Pydantic)
        7. Rate limit verification
        8. SLA timeout execution
        9. Output schema validation (Pydantic)
        10. Immutable audit logging
        """
        start_time = time.perf_counter()

        # 1. Tool existence check
        tool_entry = self.tools.get(tool_name)
        if not tool_entry:
            self._log_audit_event(tool_name, context, "NOT_FOUND", 0.0, "Tool not registered")
            raise ToolNotFoundException(tool_name=tool_name)

        tool_def, server = tool_entry

        try:
            # 2. Agent tool allowlist enforcement
            MCPSecurityValidator.validate_allowlist(context.agent_type, tool_name)

            # 3. RBAC & permissions validation
            MCPSecurityValidator.validate_rbac_permissions(tool_def, context)

            # 4. Malicious payload scan (SQLi, path traversal, shell injection)
            MCPSecurityValidator.scan_for_malicious_inputs(tool_name, arguments)

            # 5. Tenant boundary validation
            MCPSecurityValidator.validate_tenant_boundary(arguments, context)

            # 6. Input validation via Pydantic model
            try:
                validated_input_model = tool_def.input_model(**arguments)
                validated_args = validated_input_model.model_dump()
            except ValidationError as ve:
                raise ToolValidationException(tool_name=tool_name, errors=ve.errors()) from ve

            # 7. Rate limit check
            self._check_rate_limit(context.tenant_id)

            # 8. Timeout-governed tool execution
            sla_timeout = timeout_seconds or self.default_timeout_seconds
            try:
                raw_output = await asyncio.wait_for(
                    server.execute_tool(tool_name, validated_args, context),
                    timeout=sla_timeout,
                )
            except TimeoutError as te:
                raise ToolExecutionTimeoutException(tool_name=tool_name, timeout_seconds=sla_timeout) from te

            # 9. Output validation via Pydantic model
            if isinstance(raw_output, dict):
                try:
                    validated_output_model = tool_def.output_model(**raw_output)
                    validated_output = validated_output_model.model_dump()
                except ValidationError as ve:
                    raise ToolValidationException(tool_name=tool_name, errors=ve.errors()) from ve
            else:
                validated_output = raw_output

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # 10. Audit logging
            self._log_audit_event(tool_name, context, "SUCCESS", duration_ms)

            return ToolResult(
                tool_name=tool_name,
                status="SUCCESS",
                data=validated_output,
                execution_time_ms=round(duration_ms, 2),
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self._log_audit_event(tool_name, context, "FAILED", duration_ms, str(e))
            raise
