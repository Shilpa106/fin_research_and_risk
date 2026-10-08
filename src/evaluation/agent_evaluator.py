from typing import Any
from .models import AgentMetrics


class AgentEvaluator:
    """
    Multi-Agent Governance & Performance Evaluator.
    Evaluates:
    - Task Success
    - Tool Selection Accuracy
    - Tool Execution Success
    - Trajectory Correctness
    - Unnecessary Tool Calls
    - Latency (seconds)
    - Token Usage
    - Cost (USD)
    """

    @staticmethod
    def evaluate_agent(
        actual_tool_calls: list[str],
        expected_tool_calls: list[str],
        tool_execution_statuses: list[str] | None = None,
        actual_trajectory_nodes: list[str] | None = None,
        expected_trajectory_nodes: list[str] | None = None,
        termination_reason: str = "SUCCESS",
        final_response: str = "",
        latency_seconds: float = 0.0,
        token_usage: int = 0,
        cost_usd: float = 0.0,
    ) -> AgentMetrics:
        """
        Computes exact empirical evaluation metrics for an executed multi-agent run.
        """
        # 1. Task Success
        is_terminal_success = termination_reason in {"SUCCESS", "ValidationStatus.APPROVED", "APPROVED"}
        has_response = bool(final_response and len(final_response.strip()) >= 20)
        task_success = 1.0 if (is_terminal_success and has_response) else 0.0

        # 2. Tool Selection Accuracy
        expected_set = set(expected_tool_calls)
        actual_set = set(actual_tool_calls)
        if not expected_set:
            tool_selection_acc = 1.0 if not actual_set else 0.5
        else:
            correct_tools = sum(1 for t in actual_set if t in expected_set)
            tool_selection_acc = correct_tools / len(expected_set)

        # 3. Tool Execution Success Rate
        statuses = tool_execution_statuses or ["SUCCESS"] * len(actual_tool_calls)
        if not statuses:
            tool_exec_success = 1.0
        else:
            successful_calls = sum(1 for s in statuses if s.upper() in {"SUCCESS", "OK", "COMPLETED"})
            tool_exec_success = successful_calls / len(statuses)

        # 4. Trajectory Correctness
        if actual_trajectory_nodes is None and expected_trajectory_nodes is None:
            trajectory_correctness = 1.0
        else:
            trajectory_correctness = AgentEvaluator._compute_trajectory_score(
                actual=actual_trajectory_nodes or [],
                expected=expected_trajectory_nodes or ["supervisor", "synthesizer", "validator"],
            )

        # 5. Unnecessary Tool Calls
        unnecessary_count = sum(1 for t in actual_tool_calls if t not in expected_set) if expected_set else 0

        return AgentMetrics(
            task_success=round(task_success, 4),
            tool_selection_accuracy=round(min(1.0, max(0.0, tool_selection_acc)), 4),
            tool_execution_success=round(min(1.0, max(0.0, tool_exec_success)), 4),
            trajectory_correctness=round(min(1.0, max(0.0, trajectory_correctness)), 4),
            unnecessary_tool_calls=unnecessary_count,
            latency_seconds=round(latency_seconds, 3),
            token_usage=token_usage,
            cost_usd=round(cost_usd, 6),
        )

    @staticmethod
    def _compute_trajectory_score(actual: list[str], expected: list[str]) -> float:
        """
        Measures topological order alignment of agent node execution.
        """
        if not expected:
            return 1.0
        if not actual:
            return 0.0

        # Calculate longest common subsequence (LCS) ratio
        m, n = len(actual), len(expected)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m):
            for j in range(n):
                if actual[i] == expected[j]:
                    dp[i + 1][j + 1] = dp[i][j] + 1
                else:
                    dp[i + 1][j + 1] = max(dp[i + 1][j], dp[i][j + 1])

        lcs_len = dp[m][n]
        return lcs_len / max(len(expected), 1)
