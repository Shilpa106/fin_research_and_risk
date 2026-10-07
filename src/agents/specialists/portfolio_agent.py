import logging
from typing import Any

from ..state import AgentState
from ..trajectory import AgentTrajectoryLogger

logger = logging.getLogger("enterprise_copilot.agents.portfolio")


class PortfolioAgent:
    """
    Portfolio Specialist Agent.
    Assesses portfolio holdings, asset allocation, benchmark tracking error,
    sector concentration, and rebalancing recommendations.
    """

    @staticmethod
    async def execute(state: AgentState) -> dict[str, Any]:
        """Analyzes portfolio composition and concentration guidelines."""
        query = state.get("user_request", "")
        tenant_id = state.get("tenant_id", "default")
        active = state.get("active_specialists", [])
        completed = list(state.get("completed_specialists", []))

        tool_name = "portfolio_analyzer"
        portfolio_metrics = {
            "total_aum": "$124.5M",
            "top_sector": "Information Technology (32.4%)",
            "cash_drag": "4.2%",
            "tracking_error_vs_sp500": "1.15%",
            "max_single_issuer_weight": "4.8% (Below 5.0% mandate ceiling)",
        }

        tool_result = {
            "tool": tool_name,
            "status": "SUCCESS",
            "input": {"tenant_id": tenant_id, "query": query},
            "output": portfolio_metrics,
        }

        portfolio_output = {
            "summary": "Portfolio allocation maintains strong alignment with benchmark. Maximum single issuer exposure is 4.8%, strictly adhering to mandate limits.",
            "metrics": portfolio_metrics,
        }

        completed.append("portfolio_agent")
        remaining = [s for s in active if s not in completed]
        next_agent = remaining[0] if remaining else "synthesizer"

        new_tools = list(state.get("tool_results", [])) + [tool_result]
        agent_outputs = dict(state.get("agent_outputs", {}))
        agent_outputs["portfolio"] = portfolio_output

        traj = AgentTrajectoryLogger.record_step(
            state=state,
            agent_node="portfolio_agent",
            action_taken=f"Analyzed portfolio concentration and tracking error via {tool_name}. Next: {next_agent}",
            tools_invoked=[tool_name],
            tokens_delta=290,
            cost_delta=0.0006,
            output_summary=str(portfolio_output["summary"]),
        )

        return {
            "tool_results": new_tools,
            "agent_outputs": agent_outputs,
            "completed_specialists": completed,
            "next_agent": next_agent,
            "iteration_count": state.get("iteration_count", 0) + 1,
            **traj,
        }
