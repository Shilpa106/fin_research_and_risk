import logging
from typing import Any

from ..state import AgentState
from ..trajectory import AgentTrajectoryLogger

logger = logging.getLogger("enterprise_copilot.agents.supervisor")


class SupervisorAgent:
    """
    Supervisor Agent.
    Deconstructs user queries, determines analytical intent, and establishes an optimal
    multi-specialist execution plan across Research, Risk, and Portfolio agents.
    """

    @staticmethod
    async def execute(state: AgentState) -> dict[str, Any]:
        """
        Analyzes query intent and selects required specialist agents.
        """
        query = state.get("user_request", "").lower()
        active_specialists: list[str] = []

        import re

        def _has_word(words: list[str]) -> bool:
            return any(re.search(r"\b" + re.escape(w) + r"\b", query) for w in words)

        # 1. Intent Detection Heuristics
        needs_research = _has_word([
            "research", "apple", "microsoft", "nvda", "10-k", "10k", "10-q", "earnings",
            "revenue", "ebitda", "transcript", "filing", "growth", "margin", "sec", "sales", "iphone", "azure", "cloud",
        ]) or (not _has_word(["var", "portfolio", "holdings", "allocation", "concentration"]))

        needs_risk = _has_word([
            "risk", "var", "value at risk", "value-at-risk", "stress", "scenario", "volatility",
            "drawdown", "liquidity", "tail risk", "limit", "leverage", "override",
        ])

        needs_portfolio = _has_word([
            "holdings", "holding", "allocation", "weight", "rebalance",
            "concentration", "benchmark", "alpha", "beta", "fund", "sector",
        ]) or ("portfolio" in query and not needs_risk)

        if needs_research:
            active_specialists.append("research_agent")
        if needs_risk:
            active_specialists.append("risk_agent")
        if needs_portfolio:
            active_specialists.append("portfolio_agent")

        # Fallback to research agent if no specific keywords matched
        if not active_specialists:
            active_specialists.append("research_agent")

        # Prioritize risk_agent first if query is predominantly about risk/limits/override
        if any(w in query for w in ["override", "leverage", "var", "stress"]) and "risk_agent" in active_specialists:
            active_specialists.remove("risk_agent")
            active_specialists.insert(0, "risk_agent")

        # Select first pending specialist
        next_agent = active_specialists[0] if active_specialists else "synthesizer"

        traj = AgentTrajectoryLogger.record_step(
            state=state,
            agent_node="supervisor",
            action_taken=f"Intent analyzed. Planned specialists: {active_specialists}",
            tokens_delta=150,
            cost_delta=0.0003,
            output_summary=f"Specialists: {', '.join(active_specialists)}",
        )

        return {
            "active_specialists": active_specialists,
            "completed_specialists": [],
            "next_agent": next_agent,
            "iteration_count": state.get("iteration_count", 0) + 1,
            **traj,
        }
