
from ...domain.entities import RoleType
from ...security.context import RequestSecurityContext
from .models import (
    AgentSecurityResult,
    AgentSecurityState,
    SecurityViolation,
    SecurityViolationType,
    SeverityLevel,
)

# Institutional Agent Tool Allowlists
SPECIALIST_TOOL_ALLOWLISTS: dict[str, set[str]] = {
    "supervisor": {
        "get_stock_price",
        "search_research",
        "get_portfolio",
        "get_volatility",
    },
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
    "synthesizer": set(),
    "validator": set(),
}

# Required RBAC permissions per tool category
TOOL_PERMISSION_MAP: dict[str, str] = {
    "get_stock_price": "tools:execute:market",
    "get_historical_price": "tools:execute:market",
    "get_market_cap": "tools:execute:market",
    "get_volatility": "tools:execute:risk",
    "search_research": "tools:execute:research",
    "get_company_report": "tools:execute:research",
    "search_earnings": "tools:execute:research",
    "get_portfolio": "tools:execute:portfolio",
    "get_position": "tools:execute:portfolio",
    "calculate_exposure": "tools:execute:portfolio",
    "calculate_sector_exposure": "tools:execute:portfolio",
    "modify_risk_limits": "tools:execute:admin",
    "system_maintenance": "tools:execute:admin",
}

# Tools with state-modifying or high-impact operational significance requiring HITL
STATE_MODIFYING_TOOLS: set[str] = {
    "modify_risk_limits",
    "execute_rebalance",
    "system_maintenance",
    "override_compliance_rules",
}


class AgentSecurityGuard:
    """
    Enterprise Agent Runtime Governance & Sandboxing Guard.
    Enforces:
    1. Specialist tool allowlists (least-privilege)
    2. RBAC tool execution authorization
    3. Maximum iterations limit (anti-runaway loop)
    4. Maximum tool calls threshold
    5. Cost budget ceiling in USD
    6. Time budget / execution deadline
    7. Excessive agency defense (HITL gate for state-modifying tools)
    """

    def __init__(
        self,
        default_max_iterations: int = 10,
        default_max_tool_calls: int = 15,
        default_cost_budget_usd: float = 1.0,
        default_time_budget_seconds: float = 60.0,
    ):
        self.default_max_iterations = default_max_iterations
        self.default_max_tool_calls = default_max_tool_calls
        self.default_cost_budget_usd = default_cost_budget_usd
        self.default_time_budget_seconds = default_time_budget_seconds

    def create_security_state(
        self,
        agent_id: str,
        tenant_id: str,
        max_iterations: int | None = None,
        max_tool_calls: int | None = None,
        cost_budget_usd: float | None = None,
        time_budget_seconds: float | None = None,
    ) -> AgentSecurityState:
        """Initializes a new runtime governance tracker for an agent run."""
        return AgentSecurityState(
            agent_id=agent_id,
            tenant_id=tenant_id,
            max_iterations=max_iterations or self.default_max_iterations,
            max_tool_calls=max_tool_calls or self.default_max_tool_calls,
            cost_budget_usd=cost_budget_usd or self.default_cost_budget_usd,
            time_budget_seconds=time_budget_seconds or self.default_time_budget_seconds,
        )

    def validate_iteration_step(
        self,
        state: AgentSecurityState,
        iteration_index: int,
        elapsed_seconds: float,
    ) -> AgentSecurityResult:
        """
        Validates step iteration and time budget before dispatching next graph step.
        """
        violations: list[SecurityViolation] = []
        budget_exhausted = False

        state.current_iterations = iteration_index
        state.elapsed_time_seconds = elapsed_seconds

        # 1. Iteration limit check
        if iteration_index >= state.max_iterations:
            budget_exhausted = True
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.ITERATION_LIMIT_EXCEEDED,
                    severity=SeverityLevel.HIGH,
                    message=f"Agent loop halted: reached max iterations limit ({iteration_index}/{state.max_iterations}).",
                    details={"iterations": iteration_index, "limit": state.max_iterations},
                )
            )

        # 2. Time budget check
        if elapsed_seconds > state.time_budget_seconds:
            budget_exhausted = True
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.TIME_BUDGET_EXCEEDED,
                    severity=SeverityLevel.HIGH,
                    message=f"Agent timeout: elapsed time {elapsed_seconds:.1f}s exceeded budget {state.time_budget_seconds}s.",
                    details={"elapsed_seconds": elapsed_seconds, "limit_seconds": state.time_budget_seconds},
                )
            )

        is_permitted = len(violations) == 0
        return AgentSecurityResult(
            is_permitted=is_permitted,
            violations=violations,
            budget_exhausted=budget_exhausted,
        )

    def authorize_tool_invocation(
        self,
        agent_role: str,
        tool_name: str,
        state: AgentSecurityState,
        context: RequestSecurityContext,
        estimated_cost_usd: float = 0.0,
    ) -> AgentSecurityResult:
        """
        Enforces perimeter authorization and consumption quotas before executing an MCP tool.
        """
        violations: list[SecurityViolation] = []
        budget_exhausted = False
        requires_human_approval = False
        approval_reason = None

        # 1. Tool Call Count Limit
        if state.tool_calls_count >= state.max_tool_calls:
            budget_exhausted = True
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.TOOL_CALL_LIMIT_EXCEEDED,
                    severity=SeverityLevel.HIGH,
                    message=f"Tool call limit reached ({state.tool_calls_count}/{state.max_tool_calls}).",
                    details={"tool_calls": state.tool_calls_count, "limit": state.max_tool_calls},
                )
            )

        # 2. Cost Budget Limit
        if (state.accumulated_cost_usd + estimated_cost_usd) > state.cost_budget_usd:
            budget_exhausted = True
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.COST_BUDGET_EXCEEDED,
                    severity=SeverityLevel.HIGH,
                    message=(
                        f"Cost budget exceeded: accumulated ${state.accumulated_cost_usd:.4f} + "
                        f"${estimated_cost_usd:.4f} > limit ${state.cost_budget_usd:.2f}."
                    ),
                    details={
                        "accumulated_cost": state.accumulated_cost_usd,
                        "call_cost": estimated_cost_usd,
                        "budget": state.cost_budget_usd,
                    },
                )
            )

        # 3. Tool Allowlist Enforcement (Least Privilege)
        allowed_tools = SPECIALIST_TOOL_ALLOWLISTS.get(agent_role)
        if allowed_tools is not None and tool_name not in allowed_tools:
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.TOOL_ALLOWLIST_VIOLATION,
                    severity=SeverityLevel.CRITICAL,
                    message=f"Agent '{agent_role}' is not permitted to invoke tool '{tool_name}'.",
                    details={"agent_role": agent_role, "tool_name": tool_name},
                )
            )

        # 4. RBAC Tool Authorization
        required_perm = TOOL_PERMISSION_MAP.get(tool_name)
        if required_perm and not context.has_permission(required_perm):
            # Check for general wildcard or Admin bypass
            if RoleType.ADMIN not in context.roles and "tools:execute:*" not in context.permissions:
                violations.append(
                    SecurityViolation(
                        violation_type=SecurityViolationType.TOOL_AUTHORIZATION_VIOLATION,
                        severity=SeverityLevel.CRITICAL,
                        message=f"User lacks requisite permission '{required_perm}' for tool '{tool_name}'.",
                        details={"required_permission": required_perm, "tool_name": tool_name},
                    )
                )

        # 5. Excessive Agency Defense (State-modifying actions require HITL approval)
        if tool_name in STATE_MODIFYING_TOOLS:
            requires_human_approval = True
            approval_reason = f"High-impact state modification tool '{tool_name}' requires Human-in-the-Loop approval."
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.EXCESSIVE_AGENCY,
                    severity=SeverityLevel.HIGH,
                    message=approval_reason,
                    details={"tool_name": tool_name},
                )
            )

        # Record invocation if no critical allowlist/RBAC violations
        is_permitted = len([v for v in violations if v.severity == SeverityLevel.CRITICAL]) == 0 and not budget_exhausted
        if is_permitted and not requires_human_approval:
            state.tool_calls_count += 1
            state.accumulated_cost_usd += estimated_cost_usd
            state.tool_invocations.append(tool_name)

        return AgentSecurityResult(
            is_permitted=is_permitted and not requires_human_approval,
            violations=violations,
            budget_exhausted=budget_exhausted,
            requires_human_approval=requires_human_approval,
            approval_reason=approval_reason,
        )
