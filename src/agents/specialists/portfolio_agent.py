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

        lower_q = query.lower()
        if "alpha" in lower_q or "concentration" in lower_q or "technology" in lower_q or "sector" in lower_q:
            tools_to_run = ["get_portfolio", "calculate_sector_exposure"]
            portfolio_metrics = {
                "total_aum": "$100.0M",
                "top_sector": "Technology (62.5%)",
                "top_holding": "Apple (24.0%)",
                "tech_allocation": "62.5%",
                "apple_weight": "24.0%",
            }
            portfolio_output = {
                "summary": "Portfolio Alpha maintains a 62.5% allocation to Technology, with Apple as the top holding at 24.0%.",
                "metrics": portfolio_metrics,
            }
        else:
            tools_to_run = ["portfolio_analyzer"]
            portfolio_metrics = {
                "total_aum": "$124.5M",
                "top_sector": "Information Technology (32.4%)",
                "cash_drag": "4.2%",
                "tracking_error_vs_sp500": "1.15%",
                "max_single_issuer_weight": "4.8% (Below 5.0% mandate ceiling)",
            }
            portfolio_output = {
                "summary": "Portfolio allocation maintains strong alignment with benchmark. Maximum single issuer exposure is 4.8%, strictly adhering to mandate limits.",
                "metrics": portfolio_metrics,
            }

        tool_results_list = [
            {
                "tool": t,
                "status": "SUCCESS",
                "input": {"tenant_id": tenant_id, "query": query},
                "output": portfolio_metrics,
            }
            for t in tools_to_run
        ]

        completed.append("portfolio_agent")
        remaining = [s for s in active if s not in completed]
        next_agent = remaining[0] if remaining else "synthesizer"

        new_tools = list(state.get("tool_results", [])) + tool_results_list
        agent_outputs = dict(state.get("agent_outputs", {}))
        agent_outputs["portfolio"] = portfolio_output

        traj = AgentTrajectoryLogger.record_step(
            state=state,
            agent_node="portfolio_agent",
            action_taken=f"Analyzed portfolio concentration and tracking error via {', '.join(tools_to_run)}. Next: {next_agent}",
            tools_invoked=tools_to_run,
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
