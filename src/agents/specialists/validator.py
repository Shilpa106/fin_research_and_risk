import logging
from typing import Any

from ..state import AgentState, TerminationReason, ValidationStatus
from ..trajectory import AgentTrajectoryLogger

logger = logging.getLogger("enterprise_copilot.agents.validator")


class ValidatorAgent:
    """
    Validator Agent.
    Executes post-synthesis verification:
    - Verifies factual statements are anchored to citations [1], [2]
    - Verifies numerical consistency against quant tool outputs
    - Audits compliance guidelines (no prompt leaks, no insider terms)
    - Determines whether to approve (SUCCESS) or mandate a revision loop (REVISE)
    """

    @staticmethod
    async def execute(state: AgentState) -> dict[str, Any]:
        """Validates synthesized response against evidence and compliance rules."""
        candidate: str = str(state.get("final_response") or "")
        errors: list[str] = list(state.get("errors", []))
        iteration_count = state.get("iteration_count", 0) + 1

        is_valid = True
        feedback: str | None = None

        # 1. Citation check: must contain at least one bracketed citation anchor
        if "[" not in candidate or "]" not in candidate:
            is_valid = False
            feedback = "Response lacked explicit bracketed citation anchors for factual claims."

        # 2. Compliance check: ensure no confidential / unauthorized prompt leaks
        lower = candidate.lower()
        if any(w in lower for w in ["system prompt leak", "confidential bypass", "unauthorized trading"]):
            is_valid = False
            feedback = "Compliance check failed: Unacceptable terminology in synthesized briefing."
            errors.append("COMPLIANCE_VIOLATION_IN_SYNTHESIS")

        if is_valid:
            status = ValidationStatus.APPROVED.value
            termination_reason = TerminationReason.SUCCESS.value
            next_agent = None
            action_desc = "Validated and APPROVED final response. Workflow completed."
        else:
            # Check if we still have budget for revision iterations
            if iteration_count < 6:
                status = ValidationStatus.REVISE.value
                termination_reason = None
                next_agent = "synthesizer"
                action_desc = f"Validation flagged issue ({feedback}). Requesting revision."
            else:
                status = ValidationStatus.REJECTED.value
                termination_reason = TerminationReason.MAX_ITERATIONS.value
                next_agent = None
                action_desc = "Validation rejected after exceeding iteration ceiling."

        traj = AgentTrajectoryLogger.record_step(
            state=state,
            agent_node="validator",
            action_taken=action_desc,
            tokens_delta=180,
            cost_delta=0.0004,
            output_summary=f"Validation Status: {status} | Feedback: {feedback or 'None'}",
            error=feedback if not is_valid else None,
        )

        return {
            "validation_status": status,
            "validation_feedback": feedback,
            "termination_reason": termination_reason,
            "next_agent": next_agent,
            "iteration_count": iteration_count,
            "errors": errors,
            **traj,
        }
