import logging
import time
from typing import Any

from .state import AgentState

logger = logging.getLogger("enterprise_copilot.agents.trajectory")


class AgentTrajectoryLogger:
    """
    Records auditable execution trajectories across all agent state transitions.
    Never logs raw user prompts, sensitive customer data, or security keys.
    """

    @staticmethod
    def record_step(
        state: AgentState,
        agent_node: str,
        action_taken: str,
        tools_invoked: list[str] | None = None,
        tokens_delta: int = 0,
        cost_delta: float = 0.0,
        output_summary: str = "",
        error: str | None = None,
    ) -> dict[str, Any]:
        """Appends step entry to state['trajectory'] and emits structured log."""
        step_number = len(state.get("trajectory", [])) + 1
        entry: dict[str, Any] = {
            "step_number": step_number,
            "agent_node": agent_node,
            "timestamp": round(time.time(), 3),
            "action_taken": action_taken,
            "tools_invoked": tools_invoked or [],
            "tokens_delta": tokens_delta,
            "cost_delta": round(cost_delta, 6),
            "output_summary": output_summary[:200] if output_summary else "",
            "error": error,
        }

        new_trajectory = list(state.get("trajectory", [])) + [entry]
        new_tokens = state.get("tokens_used", 0) + tokens_delta
        new_cost = round(state.get("cost_accumulated", 0.0) + cost_delta, 6)

        state["trajectory"] = new_trajectory
        state["tokens_used"] = new_tokens
        state["cost_accumulated"] = new_cost

        logger.info(
            "Agent Trajectory | Step: %d | Node: %s | Action: %s | Tools: %s | "
            "TokensDelta: %d | CostDelta: $%.6f | Error: %s",
            step_number,
            agent_node,
            action_taken,
            tools_invoked or [],
            tokens_delta,
            cost_delta,
            error,
        )

        return {
            "trajectory": new_trajectory,
            "tokens_used": new_tokens,
            "cost_accumulated": new_cost,
        }
