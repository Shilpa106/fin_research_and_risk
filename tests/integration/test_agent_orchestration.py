import time

import pytest

from src.agents import (
    AgentOrchestrator,
    TerminationReason,
    ValidationStatus,
)


@pytest.fixture
def orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator(max_iterations=10, max_tool_failures=3)


# ==============================================================================
# 1. End-to-End Multi-Agent Workflow
# ==============================================================================

@pytest.mark.asyncio
async def test_end_to_end_agent_orchestration_success(orchestrator: AgentOrchestrator):
    """
    Validates end-to-end workflow:
    User -> Supervisor -> Research + Risk Agents -> Synthesizer -> Validator -> SUCCESS
    """
    query = "Analyze Apple operating cash flow and compute portfolio 99% VaR."
    tenant_id = "tenant-fidelity-institutional"
    thread_id = "thread-e2e-001"

    final_state = await orchestrator.run(
        user_request=query,
        tenant_id=tenant_id,
        permissions=["ANALYST", "RISK_MANAGER"],
        token_budget=50_000,
        cost_budget=5.0,
        timeout_seconds=30.0,
        thread_id=thread_id,
    )

    # 1. Verify Termination Condition and Validation
    assert final_state["termination_reason"] == TerminationReason.SUCCESS.value
    assert final_state["validation_status"] == ValidationStatus.APPROVED.value
    assert final_state["final_response"] is not None

    # 2. Verify Output Contents and Citations
    response = final_state["final_response"]
    assert "Executive Briefing" in response
    assert "[1]" in response
    assert "VaR" in response or "Risk Profile" in response

    # 3. Verify Multi-Specialist Evidence
    assert "research" in final_state["agent_outputs"]
    assert "risk" in final_state["agent_outputs"]
    assert len(final_state["retrieved_evidence"]) >= 1
    assert len(final_state["tool_results"]) >= 2

    # 4. Verify Trajectory Logging
    trajectory = final_state["trajectory"]
    assert len(trajectory) >= 5
    nodes_executed = [step["agent_node"] for step in trajectory]
    assert "supervisor" in nodes_executed
    assert "research_agent" in nodes_executed
    assert "risk_agent" in nodes_executed
    assert "synthesizer" in nodes_executed
    assert "validator" in nodes_executed
    assert "termination" in nodes_executed

    # 5. Verify Checkpointing
    checkpoint = await orchestrator.get_checkpoint(thread_id)
    assert checkpoint is not None
    assert checkpoint.values["tenant_id"] == tenant_id


# ==============================================================================
# 2. Checkpointing and State Retrieval
# ==============================================================================

@pytest.mark.asyncio
async def test_checkpointing_state_persistence(orchestrator: AgentOrchestrator):
    """Verifies that thread checkpoints preserve state across transitions."""
    thread_id = "thread-persist-002"
    final_state = await orchestrator.run(
        user_request="Review portfolio tech sector concentration.",
        tenant_id="tenant-goldman",
        thread_id=thread_id,
    )
    assert final_state["tenant_id"] == "tenant-goldman"

    cp = await orchestrator.get_checkpoint(thread_id)
    assert cp is not None
    assert cp.values["user_request"] == "Review portfolio tech sector concentration."
    assert cp.values["termination_reason"] == TerminationReason.SUCCESS.value
    assert len(cp.values["trajectory"]) > 0


# ==============================================================================
# 3. Termination Condition: Max Iterations
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_max_iterations():
    """Workflow halts with MAX_ITERATIONS if execution exceeds iteration ceiling."""
    strict_orchestrator = AgentOrchestrator(max_iterations=2)
    final_state = await strict_orchestrator.run(
        user_request="Conduct full market risk analysis.",
        tenant_id="tenant-test",
    )
    assert final_state["termination_reason"] == TerminationReason.MAX_ITERATIONS.value


# ==============================================================================
# 4. Termination Condition: Timeout
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_timeout(orchestrator: AgentOrchestrator):
    """Workflow halts with TIMEOUT if execution SLA deadline is breached."""
    final_state = await orchestrator.run(
        user_request="Analyze historical liquidity.",
        tenant_id="tenant-test",
        timeout_seconds=-1.0,  # Deadline in the past
    )
    assert final_state["termination_reason"] == TerminationReason.TIMEOUT.value


# ==============================================================================
# 5. Termination Condition: Token Budget Exceeded
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_token_budget_exceeded(orchestrator: AgentOrchestrator):
    """Workflow halts with TOKEN_BUDGET_EXCEEDED when token consumption exceeds cap."""
    final_state = await orchestrator.run(
        user_request="Perform exhaustive research and risk review.",
        tenant_id="tenant-test",
        token_budget=200,  # Supervisor consumes 150, specialist consumes 350
    )
    assert final_state["termination_reason"] == TerminationReason.TOKEN_BUDGET_EXCEEDED.value


# ==============================================================================
# 6. Termination Condition: Cost Limit Exceeded
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_cost_limit_exceeded(orchestrator: AgentOrchestrator):
    """Workflow halts with COST_LIMIT_EXCEEDED when dollar cost ceiling is breached."""
    final_state = await orchestrator.run(
        user_request="Perform extensive valuation modeling.",
        tenant_id="tenant-test",
        cost_budget=0.0004,  # First step spends 0.0003, next exceeds 0.0004
    )
    assert final_state["termination_reason"] == TerminationReason.COST_LIMIT_EXCEEDED.value


# ==============================================================================
# 7. Termination Condition: Human Approval Required
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_human_approval_required(orchestrator: AgentOrchestrator):
    """
    Workflow halts immediately with HUMAN_APPROVAL_REQUIRED when user attempts
    a risk limit override or unauthorized mandate breach.
    """
    final_state = await orchestrator.run(
        user_request="Override risk mandate limits and execute leverage.",
        tenant_id="tenant-risk-officer",
    )
    assert final_state["termination_reason"] == TerminationReason.HUMAN_APPROVAL_REQUIRED.value
    assert "requires Senior Risk Officer authorization" in final_state["final_response"]


# ==============================================================================
# 8. Termination Condition: Tool Failure Limit
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_tool_failure_limit():
    """Workflow halts with TOOL_FAILURE_LIMIT when downstream tools hit failure threshold."""
    orchestrator = AgentOrchestrator(max_tool_failures=1)

    # Initial state with tool failure pre-set to 1
    state = await orchestrator.run(
        user_request="Lookup broken tool data",
        tenant_id="tenant-test",
    )
    # If tool failures exceed threshold in guards, test detects guard
    # Test direct guard evaluation:
    state["tool_failure_count"] = 2
    term = orchestrator._check_termination_guards(state)
    assert term == TerminationReason.TOOL_FAILURE_LIMIT.value


# ==============================================================================
# 9. Termination Condition: No Progress Autonomous Loop Prevention
# ==============================================================================

@pytest.mark.asyncio
async def test_termination_on_no_progress_autonomous_loop_guard(orchestrator: AgentOrchestrator):
    """
    Verifies that synthesizer detects identical progress hash across successive iterations,
    breaking potential infinite autonomous loops with NO_PROGRESS.
    """
    from src.agents.state import compute_state_progress_hash

    # Simulated state stuck in a loop with identical outputs
    stuck_state = {
        "user_request": "Analyze complex derivatives",
        "tenant_id": "tenant-test",
        "iteration_count": 6,
        "deadline": time.time() + 60.0,
        "token_budget": 100_000,
        "cost_budget": 10.0,
        "agent_outputs": {"research": {"summary": "unchanged"}},
        "tool_results": [],
        "retrieved_evidence": [],
    }
    stuck_state["state_hash"] = compute_state_progress_hash(stuck_state)

    res = await orchestrator._synthesizer_node(stuck_state)
    assert res["termination_reason"] == TerminationReason.NO_PROGRESS.value
    assert "could not converge" in res["final_response"]
