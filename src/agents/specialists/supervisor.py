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

        # 1. Intent Detection Heuristics
        # Research needed: company filings, fundamentals, earnings, transcripts, macro data
        needs_research = any(
            k in query for k in [
                "research", "apple", "microsoft", "nvda", "10-k", "10k", "10-q", "earnings",
                "revenue", "ebitda", "transcript", "filing", "growth", "margin", "sec",
            ]
        ) or not ("var" in query or "portfolio" in query)

        # Risk needed: VaR, stress tests, volatility, drawdown, tail risk, credit exposure
        needs_risk = any(
            k in query for k in [
                "risk", "var", "value at risk", "stress", "scenario", "volatility",
                "drawdown", "liquidity", "tail risk", "limit", "exposure", "credit",
            ]
        )

        # Portfolio needed: holdings, allocation, rebalancing, concentration, portfolio metrics
        needs_portfolio = any(
            k in query for k in [
                "portfolio", "holding", "holdings", "allocation", "weight", "rebalance",
                "concentration", "benchmark", "alpha", "beta", "fund",
            ]
        )

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
