from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.entities import AuditActionStatus
from ..domain.exceptions import AuthorizationException
from ..security.audit import record_security_audit_event
from ..security.context import RequestSecurityContext

# Define permission requirements per tool category
TOOL_PERMISSION_REQUIREMENTS: dict[str, str] = {
    "sec_edgar_lookup": "tools:execute:research",
    "market_data_quote": "tools:execute:research",
    "portfolio_var_simulator": "tools:execute:risk",
    "portfolio_stress_test": "tools:execute:risk",
    "modify_risk_limits": "tools:execute:admin",
    "system_maintenance": "tools:execute:admin",
}

class AgentToolSecurityGuard:
    """
    Enforces authorization at the Agent/Tool execution layer.
    Guarantees:
    1. Tool caller possesses the requisite role/permission.
    2. Tool executes strictly within the authenticated tenant boundary.
    3. Unauthorized attempts generate immutable security audit events.
    """

    @staticmethod
    async def authorize_tool_call(
        tool_name: str,
        target_tenant_id: str,
        context: RequestSecurityContext,
        session: AsyncSession | None = None
    ) -> None:
        """
        Validates tool execution permissions and tenant isolation.
        Raises AuthorizationException if unauthorized.
        """
        # 1. Tenant boundary enforcement at tool layer
        if context.tenant_id != target_tenant_id:
            if session:
                await record_security_audit_event(
                    session=session,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    action="UNAUTHORIZED_CROSS_TENANT_TOOL_CALL",
                    status=AuditActionStatus.DENIED,
                    resource_type="AGENT_TOOL",
                    resource_id=tool_name,
                    request_id=context.request_id,
                    details={"target_tenant_id": target_tenant_id, "tool_name": tool_name}
                )
            raise AuthorizationException(
                f"Agent Tool security violation: Tenant '{context.tenant_id}' cannot invoke tool on target tenant '{target_tenant_id}'."
            )

        # 2. Permission check for tool category
        required_perm = TOOL_PERMISSION_REQUIREMENTS.get(tool_name, "tools:execute:research")
        if not context.has_permission(required_perm):
            if session:
                await record_security_audit_event(
                    session=session,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    action="UNAUTHORIZED_TOOL_INVOCATION",
                    status=AuditActionStatus.DENIED,
                    resource_type="AGENT_TOOL",
                    resource_id=tool_name,
                    request_id=context.request_id,
                    details={"missing_permission": required_perm, "tool_name": tool_name}
                )
            raise AuthorizationException(
                f"Agent Tool permission denied: User lacks '{required_perm}' required to execute tool '{tool_name}'."
            )

def secure_agent_tool(tool_name: str):
    """Decorator for wrapping agent tool call functions with security verification."""
    def decorator(func: Callable):
        async def wrapper(*args, target_tenant_id: str, context: RequestSecurityContext, session: AsyncSession | None = None, **kwargs) -> Any:
            await AgentToolSecurityGuard.authorize_tool_call(
                tool_name=tool_name,
                target_tenant_id=target_tenant_id,
                context=context,
                session=session
            )
            return await func(*args, target_tenant_id=target_tenant_id, context=context, **kwargs)
        return wrapper
    return decorator
