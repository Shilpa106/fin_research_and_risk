from typing import Any

from ...security.context import RequestSecurityContext
from .agent_guard import AgentSecurityGuard
from .input_guard import InputSecurityGuard
from .models import (
    AgentSecurityResult,
    AgentSecurityState,
    InputSecurityResult,
    OutputSecurityResult,
    RetrievalSecurityResult,
)
from .output_guard import OutputSecurityGuard
from .retrieval_guard import RetrievalSecurityGuard


class GenAISecurityManager:
    """
    Unified Orchestrator for Multi-Layered GenAI Defense-in-Depth.
    Covers the full lifecycle of an enterprise GenAI interaction:
    1. Input Perimeter: Prompt injection, malicious instruction, PII redaction, size caps.
    2. Retrieval Layer: Multi-tenant bounds, permissions, clearance level, indirect injection.
    3. Agent Execution: Least-privilege tool allowlists, RBAC authorization, loops & cost quotas.
    4. Output Verification: Grounding, citations, SEC/FINRA disclaimers, data exfiltration defense.
    """

    def __init__(
        self,
        input_guard: InputSecurityGuard | None = None,
        retrieval_guard: RetrievalSecurityGuard | None = None,
        agent_guard: AgentSecurityGuard | None = None,
        output_guard: OutputSecurityGuard | None = None,
    ):
        self.input_guard = input_guard or InputSecurityGuard()
        self.retrieval_guard = retrieval_guard or RetrievalSecurityGuard()
        self.agent_guard = agent_guard or AgentSecurityGuard()
        self.output_guard = output_guard or OutputSecurityGuard()

    # --------------------------------------------------------------------------
    # 1. Input Security Phase
    # --------------------------------------------------------------------------
    def evaluate_input(self, prompt: str, user_id: str | None = None) -> InputSecurityResult:
        """Evaluates user prompt prior to routing or LLM invocation."""
        return self.input_guard.validate_input(prompt=prompt, user_id=user_id)

    # --------------------------------------------------------------------------
    # 2. Retrieval Security Phase
    # --------------------------------------------------------------------------
    def evaluate_retrieved_context(
        self,
        chunks: list[dict[str, Any]],
        context: RequestSecurityContext,
    ) -> RetrievalSecurityResult:
        """Filters retrieved document chunks for tenant bounds, permissions, clearance, and indirect injection."""
        return self.retrieval_guard.evaluate_retrieved_chunks(chunks=chunks, context=context)

    # --------------------------------------------------------------------------
    # 3. Agent Security Phase
    # --------------------------------------------------------------------------
    def create_agent_state(
        self,
        agent_id: str,
        tenant_id: str,
        max_iterations: int | None = None,
        max_tool_calls: int | None = None,
        cost_budget_usd: float | None = None,
        time_budget_seconds: float | None = None,
    ) -> AgentSecurityState:
        """Creates state tracker for monitoring agent execution budget and tool calls."""
        return self.agent_guard.create_security_state(
            agent_id=agent_id,
            tenant_id=tenant_id,
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
            cost_budget_usd=cost_budget_usd,
            time_budget_seconds=time_budget_seconds,
        )

    def validate_agent_step(
        self,
        state: AgentSecurityState,
        iteration_index: int,
        elapsed_seconds: float,
    ) -> AgentSecurityResult:
        """Validates agent iteration count and time budget."""
        return self.agent_guard.validate_iteration_step(
            state=state,
            iteration_index=iteration_index,
            elapsed_seconds=elapsed_seconds,
        )

    def authorize_tool(
        self,
        agent_role: str,
        tool_name: str,
        state: AgentSecurityState,
        context: RequestSecurityContext,
        estimated_cost_usd: float = 0.0,
    ) -> AgentSecurityResult:
        """Authorizes MCP tool execution against agent allowlist, RBAC, quotas, and excessive agency gates."""
        return self.agent_guard.authorize_tool_invocation(
            agent_role=agent_role,
            tool_name=tool_name,
            state=state,
            context=context,
            estimated_cost_usd=estimated_cost_usd,
        )

    # --------------------------------------------------------------------------
    # 4. Output Security Phase
    # --------------------------------------------------------------------------
    def evaluate_output(
        self,
        output_text: str,
        retrieved_chunks: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> OutputSecurityResult:
        """Evaluates synthesized model response for grounding, citations, disclaimers, and exfiltration."""
        return self.output_guard.validate_output(
            output_text=output_text,
            retrieved_chunks=retrieved_chunks,
            tool_results=tool_results,
        )
