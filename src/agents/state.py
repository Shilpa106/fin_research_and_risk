import enum
import hashlib
import json
import time
from typing import Any, TypedDict


class TerminationReason(str, enum.Enum):
    """Institutional Agent Execution Termination Conditions."""
    SUCCESS = "SUCCESS"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    TIMEOUT = "TIMEOUT"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"
    NO_PROGRESS = "NO_PROGRESS"
    TOOL_FAILURE_LIMIT = "TOOL_FAILURE_LIMIT"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    UNRECOVERABLE_ERROR = "UNRECOVERABLE_ERROR"


class ValidationStatus(str, enum.Enum):
    """Verification state evaluated by the Validator agent."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVISE = "REVISE"
    REJECTED = "REJECTED"


class AgentState(TypedDict, total=False):
    """
    Explicit, strictly typed state object passed across LangGraph nodes.
    Contains only what is strictly required for financial copilot orchestration.
    """
    # 1. User & Security Context
    user_request: str
    tenant_id: str
    permissions: list[str]
    conversation_context: list[dict[str, Any]]

    # 2. Knowledge & Execution Data
    retrieved_evidence: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    agent_outputs: dict[str, Any]
    errors: list[str]

    # 3. Governance, Budgets & Deadlines
    iteration_count: int
    token_budget: int
    cost_budget: float
    tokens_used: int
    cost_accumulated: float
    deadline: float

    # 4. Orchestration & Validation
    validation_status: str
    validation_feedback: str | None
    next_agent: str | None
    active_specialists: list[str]
    completed_specialists: list[str]
    tool_failure_count: int

    # 5. Output & Trajectory
    termination_reason: str | None
    final_response: str | None
    trajectory: list[dict[str, Any]]
    state_hash: str | None


def compute_state_progress_hash(state: AgentState) -> str:
    """
    Generates a deterministic digest of the agent outputs and tool results.
    Used to detect infinite autonomous loops where no new progress is being made.
    """
    payload = {
        "outputs": state.get("agent_outputs", {}),
        "tool_results_len": len(state.get("tool_results", [])),
        "evidence_len": len(state.get("retrieved_evidence", [])),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def create_initial_state(
    user_request: str,
    tenant_id: str,
    permissions: list[str] | None = None,
    conversation_context: list[dict[str, Any]] | None = None,
    token_budget: int = 100_000,
    cost_budget: float = 10.0,
    timeout_seconds: float = 60.0,
) -> AgentState:
    """Factory creating a well-formed initial AgentState envelope."""
    now = time.time()
    return AgentState(
        user_request=user_request,
        tenant_id=tenant_id,
        permissions=permissions or ["ANALYST"],
        conversation_context=conversation_context or [],
        retrieved_evidence=[],
        tool_results=[],
        agent_outputs={},
        errors=[],
        iteration_count=0,
        token_budget=token_budget,
        cost_budget=cost_budget,
        tokens_used=0,
        cost_accumulated=0.0,
        deadline=now + timeout_seconds,
        validation_status=ValidationStatus.PENDING.value,
        validation_feedback=None,
        next_agent="supervisor",
        active_specialists=[],
        completed_specialists=[],
        tool_failure_count=0,
        termination_reason=None,
        final_response=None,
        trajectory=[],
        state_hash="",
    )
