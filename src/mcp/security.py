import re
from typing import Any

from ..domain.exceptions import (
    AuthorizationException,
    MaliciousInputDetectedException,
    TenantIsolationViolationException,
)
from .models import ToolDefinition, ToolSecurityContext

# Institutional Agent Tool Allowlists
# Agents are restricted exclusively to their least-privilege domain tools.
AGENT_TOOL_ALLOWLISTS: dict[str, set[str]] = {
    "research_agent": {
        "get_stock_price",
        "get_historical_price",
        "get_market_cap",
        "search_research",
        "get_company_report",
        "search_earnings",
    },
    "risk_agent": {
        "get_stock_price",
        "get_volatility",
        "calculate_exposure",
        "calculate_sector_exposure",
    },
    "portfolio_agent": {
        "get_stock_price",
        "get_portfolio",
        "get_position",
        "calculate_exposure",
        "calculate_sector_exposure",
    },
}

# Malicious Pattern Signatures
MALICIOUS_PATTERNS = [
    (r"(\.\./|\.\.\\)", "PATH_TRAVERSAL_ATTEMPT"),
    (r"(;\s*(?:rm|cat|echo|wget|curl|bash|sh|powershell)\b|&&|\|\||`|\$\()", "COMMAND_INJECTION_ATTEMPT"),
    (r"(\bUNION\s+SELECT\b|;\s*DROP\s+TABLE\b|'\s*OR\s*['\d\w\s]+=|\bSELECT\s+\*\s+FROM\b|--)", "SQL_INJECTION_ATTEMPT"),
    (r"(<script\b|javascript:|onerror=)", "XSS_SCRIPT_INJECTION"),
    (r"(ignore\s+previous\s+instructions|system\s+prompt\s+leak|bypass\s+all\s+guardrails)", "PROMPT_INJECTION_EXPLOIT"),
]


class MCPSecurityValidator:
    """
    Enforces perimeter defense across all Model Context Protocol (MCP) tool invocations:
    - Agent tool allowlist enforcement
    - Malicious input payload detection (SQLi, command injection, path traversal)
    - Strict tenant isolation boundary checks
    - Role-based and permission-based authorization
    """

    @staticmethod
    def validate_allowlist(agent_type: str | None, tool_name: str) -> None:
        """
        Verifies that the invoking agent is explicitly allowed to execute tool_name.
        The agent must NEVER have unrestricted access to arbitrary APIs.
        """
        if agent_type is None:
            return  # Direct user/system call governed by RBAC permissions

        allowed = AGENT_TOOL_ALLOWLISTS.get(agent_type)
        if allowed is None or tool_name not in allowed:
            raise AuthorizationException(
                f"Security Allowlist Violation: Agent '{agent_type}' is forbidden from invoking tool '{tool_name}'."
            )

    @staticmethod
    def scan_for_malicious_inputs(tool_name: str, arguments: dict[str, Any]) -> None:
        """
        Recursively inspects argument values against known malicious pattern signatures.
        Raises MaliciousInputDetectedException if any payload signature matches.
        """
        def _check_val(val: Any) -> None:
            if isinstance(val, str):
                for pattern, violation_type in MALICIOUS_PATTERNS:
                    if re.search(pattern, val, re.IGNORECASE):
                        raise MaliciousInputDetectedException(
                            tool_name=tool_name,
                            violation_type=violation_type,
                            details=f"Signature '{pattern}' detected in argument payload.",
                        )
            elif isinstance(val, dict):
                for v in val.values():
                    _check_val(v)
            elif isinstance(val, list):
                for item in val:
                    _check_val(item)

        _check_val(arguments)

    @staticmethod
    def validate_tenant_boundary(arguments: dict[str, Any], context: ToolSecurityContext) -> None:
        """
        Validates that arguments carrying tenant_id match the authenticated caller's tenant_id.
        Prevents cross-tenant parameter tampering.
        """
        arg_tenant = arguments.get("tenant_id")
        if arg_tenant and arg_tenant != context.tenant_id:
            raise TenantIsolationViolationException(
                f"Cross-tenant tool invocation blocked: Caller '{context.tenant_id}' cannot access target '{arg_tenant}'."
            )

    @staticmethod
    def validate_rbac_permissions(tool_def: ToolDefinition, context: ToolSecurityContext) -> None:
        """
        Verifies caller has requisite RBAC permissions and roles.
        """
        # 1. Admin bypass
        if "ADMIN" in context.roles:
            return

        # 2. Role check
        if tool_def.allowed_roles and not any(r in context.roles for r in tool_def.allowed_roles):
            raise AuthorizationException(
                f"Caller lacks required role to invoke tool '{tool_def.name}' (Requires: {tool_def.allowed_roles})."
            )

        # 3. Permission check
        if tool_def.required_permission and tool_def.required_permission not in context.permissions:
            # Also allow general category wildcard (e.g. tools:execute:market)
            cat_perm = f"tools:execute:{tool_def.category}"
            if cat_perm not in context.permissions and "tools:execute:*" not in context.permissions:
                raise AuthorizationException(
                    f"Caller lacks permission '{tool_def.required_permission}' for tool '{tool_def.name}'."
                )
