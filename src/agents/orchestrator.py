import logging
import time
import uuid
from typing import Any, cast

from ..observability.context import agent_run_id_ctx
from ..observability.integrations import langsmith_exporter
from ..observability.metrics import metrics_registry
from ..observability.tracing import SpanKind, default_tracer

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ..domain.exceptions import EntityNotFoundException
from .specialists.portfolio_agent import PortfolioAgent
from .specialists.research_agent import ResearchAgent
from .specialists.risk_agent import RiskAgent
from .specialists.supervisor import SupervisorAgent
from .specialists.synthesizer import SynthesizerAgent
from .specialists.validator import ValidatorAgent
from .state import (
    AgentState,
    TerminationReason,
    ValidationStatus,
    compute_state_progress_hash,
    create_initial_state,
)
from .trajectory import AgentTrajectoryLogger

logger = logging.getLogger("enterprise_copilot.agents.orchestrator")


class AgentOrchestrator:
    """
    Enterprise LangGraph Agent Orchestrator.
    Executes stateful multi-agent workflows with strict governance, checkpointers,
    loop protection, budget enforcement, and explicit termination conditions.
    """

    def __init__(
        self,
        max_iterations: int = 10,
        max_tool_failures: int = 3,
        checkpointer: Any | None = None,
    ):
        self.max_iterations = max_iterations
        self.max_tool_failures = max_tool_failures
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = self._build_graph()

    def _check_termination_guards(self, state: AgentState) -> str | None:
        """
        Evaluates explicit institutional termination boundaries before any state transition.
        """
        # 1. Human Approval Required
        if state.get("termination_reason") == TerminationReason.HUMAN_APPROVAL_REQUIRED.value:
            return TerminationReason.HUMAN_APPROVAL_REQUIRED.value

        # 2. Timeout SLA
        now = time.time()
        if now >= state.get("deadline", now + 60.0):
            return TerminationReason.TIMEOUT.value

        # 3. Token Budget Exceeded
        if state.get("tokens_used", 0) >= state.get("token_budget", 100_000):
            return TerminationReason.TOKEN_BUDGET_EXCEEDED.value

        # 4. Cost Limit Exceeded
        if state.get("cost_accumulated", 0.0) >= state.get("cost_budget", 10.0):
            return TerminationReason.COST_LIMIT_EXCEEDED.value

        # 5. Max Iterations
        if state.get("iteration_count", 0) >= self.max_iterations:
            return TerminationReason.MAX_ITERATIONS.value

        # 6. Tool Failure Limit
        if state.get("tool_failure_count", 0) >= self.max_tool_failures:
            return TerminationReason.TOOL_FAILURE_LIMIT.value

        # 7. Success Check
        if state.get("validation_status") == ValidationStatus.APPROVED.value:
            return TerminationReason.SUCCESS.value

        return None

    # =========================================================================
    # Node Wrappers with Safe Execution and Telemetry
    # =========================================================================

    async def _supervisor_node(self, state: AgentState) -> dict[str, Any]:
        """Supervisor entrypoint node."""
        term = self._check_termination_guards(state)
        if term:
            return {"termination_reason": term}
        return await SupervisorAgent.execute(state)

    async def _research_node(self, state: AgentState) -> dict[str, Any]:
        """Research specialist node."""
        term = self._check_termination_guards(state)
        if term:
            return {"termination_reason": term}
        return await ResearchAgent.execute(state)

    async def _risk_node(self, state: AgentState) -> dict[str, Any]:
        """Risk specialist node."""
        term = self._check_termination_guards(state)
        if term:
            return {"termination_reason": term}
        return await RiskAgent.execute(state)

    async def _portfolio_node(self, state: AgentState) -> dict[str, Any]:
        """Portfolio specialist node."""
        term = self._check_termination_guards(state)
        if term:
            return {"termination_reason": term}
        return await PortfolioAgent.execute(state)

    async def _synthesizer_node(self, state: AgentState) -> dict[str, Any]:
        """Synthesis node."""
        term = self._check_termination_guards(state)
        if term:
            return {"termination_reason": term}

        # Check progress hash to eliminate infinite revision loops (NO_PROGRESS guard)
        current_hash = compute_state_progress_hash(state)
        last_hash = state.get("state_hash")
        if last_hash and current_hash == last_hash and state.get("iteration_count", 0) > 4:
            logger.warning("No progress detected across successive revision cycles. Halting.")
            return {
                "termination_reason": TerminationReason.NO_PROGRESS.value,
                "final_response": state.get("final_response") or "Workflow halted: Synthesis could not converge.",
            }

        res = await SynthesizerAgent.execute(state)
        res["state_hash"] = current_hash
        return res

    async def _validator_node(self, state: AgentState) -> dict[str, Any]:
        """Validator verification node."""
        term = self._check_termination_guards(state)
        if term:
            return {"termination_reason": term}
        return await ValidatorAgent.execute(state)

    async def _termination_node(self, state: AgentState) -> dict[str, Any]:
        """Finalization node formatting terminal responses."""
        reason = state.get("termination_reason") or self._check_termination_guards(state) or TerminationReason.SUCCESS.value
        response = state.get("final_response")

        if not response:
            if reason == TerminationReason.TIMEOUT.value:
                response = "Execution terminated: Request SLA deadline exceeded."
            elif reason == TerminationReason.TOKEN_BUDGET_EXCEEDED.value:
                response = "Execution terminated: Allocated token budget ceiling exhausted."
            elif reason == TerminationReason.COST_LIMIT_EXCEEDED.value:
                response = "Execution terminated: Tenant financial cost ceiling reached."
            elif reason == TerminationReason.NO_PROGRESS.value:
                response = "Execution terminated: Reasoning loop halted due to zero convergence progress."
            elif reason == TerminationReason.TOOL_FAILURE_LIMIT.value:
                response = "Execution terminated: Downstream financial tool failures exceeded threshold."
            elif reason == TerminationReason.HUMAN_APPROVAL_REQUIRED.value:
                response = "Action halted: Overriding institutional risk limits requires Human-in-the-Loop approval."
            elif reason == TerminationReason.MAX_ITERATIONS.value:
                response = "Execution terminated: Maximum multi-agent orchestration iterations reached."
            else:
                response = "Execution completed."

        traj = AgentTrajectoryLogger.record_step(
            state=state,
            agent_node="termination",
            action_taken=f"Workflow halted with reason: {reason}",
            output_summary=response[:120],
        )

        return {
            "termination_reason": reason,
            "final_response": response,
            **traj,
        }

    # =========================================================================
    # Conditional Routing Logic
    # =========================================================================

    def _route_after_step(self, state: AgentState) -> str:
        """Determines the next edge based on state conditions."""
        # 1. Termination condition active
        if state.get("termination_reason") is not None:
            return "termination"

        term = self._check_termination_guards(state)
        if term:
            state["termination_reason"] = term
            return "termination"

        # 2. Next agent dispatch
        next_agent = state.get("next_agent")
        if next_agent and next_agent in ["research_agent", "risk_agent", "portfolio_agent", "synthesizer", "validator"]:
            return next_agent

        # Default fallback: if specialists completed, synthesize
        active = state.get("active_specialists", [])
        completed = state.get("completed_specialists", [])
        remaining = [s for s in active if s not in completed]
        if remaining:
            return remaining[0]

        if state.get("validation_status") == ValidationStatus.APPROVED.value:
            return "termination"

        return "synthesizer"

    # =========================================================================
    # Graph Construction
    # =========================================================================

    def _build_graph(self) -> Any:
        """Constructs and compiles the stateful LangGraph workflow."""
        builder = StateGraph(AgentState)

        # 1. Register Nodes
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("research_agent", self._research_node)
        builder.add_node("risk_agent", self._risk_node)
        builder.add_node("portfolio_agent", self._portfolio_node)
        builder.add_node("synthesizer", self._synthesizer_node)
        builder.add_node("validator", self._validator_node)
        builder.add_node("termination", self._termination_node)

        # 2. Register Edges
        builder.add_edge(START, "supervisor")

        for node_name in ["supervisor", "research_agent", "risk_agent", "portfolio_agent", "synthesizer", "validator"]:
            builder.add_conditional_edges(
                node_name,
                self._route_after_step,
                {
                    "research_agent": "research_agent",
                    "risk_agent": "risk_agent",
                    "portfolio_agent": "portfolio_agent",
                    "synthesizer": "synthesizer",
                    "validator": "validator",
                    "termination": "termination",
                },
            )

        builder.add_edge("termination", END)

        # 3. Compile with Checkpointer
        return builder.compile(checkpointer=self.checkpointer)

    # =========================================================================
    # Public Execution APIs
    # =========================================================================

    async def run(
        self,
        user_request: str,
        tenant_id: str,
        permissions: list[str] | None = None,
        conversation_context: list[dict[str, Any]] | None = None,
        token_budget: int = 100_000,
        cost_budget: float = 10.0,
        timeout_seconds: float = 60.0,
        thread_id: str | None = None,
    ) -> AgentState:
        """Executes full multi-agent orchestration pipeline."""
        initial_state = create_initial_state(
            user_request=user_request,
            tenant_id=tenant_id,
            permissions=permissions,
            conversation_context=conversation_context,
            token_budget=token_budget,
            cost_budget=cost_budget,
            timeout_seconds=timeout_seconds,
        )

        tid = thread_id or f"thread-{int(time.time() * 1000)}"
        config = {"configurable": {"thread_id": tid}}
        agent_run_id = f"run-{uuid.uuid4().hex[:12]}"
        agent_run_id_ctx.set(agent_run_id)

        start_time = time.time()
        with default_tracer.start_as_current_span(
            "agent.orchestrator",
            kind=SpanKind.INTERNAL,
            attributes={
                "agent.thread_id": tid,
                "agent.run_id": agent_run_id,
                "tenant.id": tenant_id,
            },
        ) as span:
            final_state = await self.graph.ainvoke(initial_state, config=config)
            duration = time.time() - start_time

            iterations = final_state.get("iteration_count", 1)
            tool_calls = len(final_state.get("tool_results", []))
            term_reason = final_state.get("termination_reason")
            is_success = term_reason in (None, "SUCCESS", TerminationReason.SUCCESS.value)

            span.set_attributes({
                "agent.iterations": iterations,
                "agent.tool_calls_count": tool_calls,
                "agent.termination_reason": str(term_reason),
                "agent.is_success": is_success,
            })

            # Record Agent Observability Golden Signals
            metrics_registry.record_agent_execution(
                duration_seconds=duration,
                iterations=iterations,
                tool_calls_count=tool_calls,
                is_success=is_success,
                tenant_id=tenant_id,
            )

            # Capture LangSmith trace
            langsmith_exporter.capture_run(
                name="agent.orchestrator",
                run_type="chain",
                inputs={"user_request": user_request, "thread_id": tid},
                outputs={"final_response": final_state.get("final_response"), "termination_reason": term_reason},
                start_time=start_time,
                end_time=time.time(),
                total_tokens=final_state.get("tokens_used", 0),
                cost_usd=final_state.get("cost_accumulated", 0.0),
                tenant_id=tenant_id,
            )

        return final_state

    async def get_checkpoint(self, thread_id: str) -> Any:
        """Retrieves checkpoint state for given thread ID."""
        config = {"configurable": {"thread_id": thread_id}}
        return self.graph.get_state(config)

    async def resume_workflow(
        self,
        thread_id: str,
        approval_decision: str,
        reviewer_notes: str | None = None,
    ) -> AgentState:
        """
        Resumes a paused workflow awaiting human approval from its checkpointer state.
        If APPROVED: clears termination reason, sets validation_status to APPROVED, and completes workflow.
        If REJECTED: marks workflow explicitly rejected.
        """
        config = {"configurable": {"thread_id": thread_id}}
        current_state_snapshot = self.graph.get_state(config)

        if not current_state_snapshot or not current_state_snapshot.values:
            raise EntityNotFoundException("AgentStateCheckpoint", thread_id)

        current_values = dict(current_state_snapshot.values)

        if approval_decision.upper() in {"APPROVED", "APPROVE"}:
            current_values["termination_reason"] = None
            current_values["validation_status"] = ValidationStatus.APPROVED.value
            current_values["validation_feedback"] = f"Human Approval Granted: {reviewer_notes or 'Approved by reviewer.'}"
            current_values["final_response"] = (
                f"{current_values.get('final_response', '')} [Human Approval Granted: {reviewer_notes or 'Operation approved.'}]"
            ).strip()
            # Update checkpoint state and finalize
            self.graph.update_state(config, current_values)
            return cast(AgentState, current_values)
        else:
            current_values["termination_reason"] = "REJECTED_BY_HUMAN"
            current_values["validation_status"] = ValidationStatus.REJECTED.value
            current_values["final_response"] = f"Operation rejected by human reviewer: {reviewer_notes or 'Rejected.'}"
            self.graph.update_state(config, current_values)
            return cast(AgentState, current_values)

