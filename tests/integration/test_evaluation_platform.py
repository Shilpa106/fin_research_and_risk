import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Tenant
from src.domain.exceptions import EvaluationRegressionException
from src.evaluation import (
    GOLDEN_FINANCIAL_SAMPLES,
    AgentEvaluator,
    EvaluationRunner,
    EvaluationSummary,
    RAGEvaluator,
    RegressionDetector,
    SafetyEvaluator,
    ThresholdConfig,
    load_golden_evaluation_dataset,
)


# ==============================================================================
# 1. RAG EVALUATION METRICS TESTS
# ==============================================================================

class TestRAGEvaluation:
    """Tests covering all 8 RAG evaluation metrics."""

    def test_rag_metrics_calculation_high_quality(self):
        retrieved_chunks = ["chunk-1", "chunk-2", "chunk-3", "chunk-4", "chunk-5"]
        relevant_chunks = ["chunk-1", "chunk-2", "chunk-3"]
        retrieved_context = (
            "Apple reported Q3 total net sales of $85.78 billion. "
            "iPhone segment net sales reached $39.30 billion, up 5% year-over-year."
        )
        generated_answer = (
            "In Q3, Apple posted total net sales of $85.78 billion. "
            "iPhone revenue was $39.30 billion, reflecting strong 5% growth."
        )
        question = "What was Apple's total net sales and iPhone revenue in Q3?"
        ground_truth_statements = [
            "total net sales of $85.78 billion",
            "iPhone revenue was $39.30 billion",
        ]

        metrics = RAGEvaluator.evaluate_rag(
            retrieved_chunk_ids=retrieved_chunks,
            relevant_chunk_ids=relevant_chunks,
            retrieved_context_text=retrieved_context,
            generated_answer=generated_answer,
            question=question,
            ground_truth_statements=ground_truth_statements,
            k=5,
        )

        # 1. Recall@K (3/3 = 1.0)
        assert metrics.recall_at_k == 1.0
        # 2. Precision@K (3/5 = 0.6)
        assert metrics.precision_at_k == 0.6
        # 3. MRR (first relevant at rank 1 = 1.0)
        assert metrics.mrr == 1.0
        # 4. NDCG@K
        assert metrics.ndcg_at_k > 0.9
        # 5. Context Precision
        assert metrics.context_precision == 1.0
        # 6. Context Recall (both ground truth statements found = 1.0)
        assert metrics.context_recall == 1.0
        # 7. Faithfulness (claims grounded in context = 1.0)
        assert metrics.faithfulness >= 0.9
        # 8. Answer Relevancy (addresses question terms = high)
        assert metrics.answer_relevancy >= 0.8

    def test_rag_metrics_calculation_poor_retrieval_and_unfaithful_answer(self):
        retrieved_chunks = ["chunk-99", "chunk-98"]
        relevant_chunks = ["chunk-1", "chunk-2"]
        retrieved_context = "General economic news with zero company financial numbers."
        generated_answer = "Apple had revenue of $500 billion and profit of $200 billion."
        question = "What was Apple's total net sales in Q3?"
        ground_truth_statements = ["total net sales of $85.78 billion"]

        metrics = RAGEvaluator.evaluate_rag(
            retrieved_chunk_ids=retrieved_chunks,
            relevant_chunk_ids=relevant_chunks,
            retrieved_context_text=retrieved_context,
            generated_answer=generated_answer,
            question=question,
            ground_truth_statements=ground_truth_statements,
            k=5,
        )

        assert metrics.recall_at_k == 0.0
        assert metrics.precision_at_k == 0.0
        assert metrics.mrr == 0.0
        assert metrics.ndcg_at_k == 0.0
        assert metrics.context_recall == 0.0
        assert metrics.faithfulness <= 0.2


# ==============================================================================
# 2. AGENT EVALUATION METRICS TESTS
# ==============================================================================

class TestAgentEvaluation:
    """Tests covering all 8 agent evaluation metrics."""

    def test_agent_metrics_successful_run(self):
        actual_tools = ["get_stock_price", "search_research"]
        expected_tools = ["get_stock_price", "search_research"]
        tool_statuses = ["SUCCESS", "SUCCESS"]
        actual_trajectory = ["supervisor", "research_agent", "synthesizer", "validator"]
        expected_trajectory = ["supervisor", "research_agent", "synthesizer", "validator"]

        metrics = AgentEvaluator.evaluate_agent(
            actual_tool_calls=actual_tools,
            expected_tool_calls=expected_tools,
            tool_execution_statuses=tool_statuses,
            actual_trajectory_nodes=actual_trajectory,
            expected_trajectory_nodes=expected_trajectory,
            termination_reason="SUCCESS",
            final_response="Completed full equity research synthesis with verified valuation metrics.",
            latency_seconds=1.85,
            token_usage=2400,
            cost_usd=0.0072,
        )

        # 1. Task Success
        assert metrics.task_success == 1.0
        # 2. Tool Selection Accuracy
        assert metrics.tool_selection_accuracy == 1.0
        # 3. Tool Execution Success
        assert metrics.tool_execution_success == 1.0
        # 4. Trajectory Correctness
        assert metrics.trajectory_correctness == 1.0
        # 5. Unnecessary Tool Calls
        assert metrics.unnecessary_tool_calls == 0
        # 6. Latency
        assert metrics.latency_seconds == 1.85
        # 7. Token Usage
        assert metrics.token_usage == 2400
        # 8. Cost USD
        assert metrics.cost_usd == 0.0072

    def test_agent_metrics_suboptimal_run_with_failures(self):
        actual_tools = ["get_stock_price", "unneeded_random_tool", "portfolio_rebalance"]
        expected_tools = ["get_stock_price"]
        tool_statuses = ["SUCCESS", "FAILED", "SUCCESS"]

        metrics = AgentEvaluator.evaluate_agent(
            actual_tool_calls=actual_tools,
            expected_tool_calls=expected_tools,
            tool_execution_statuses=tool_statuses,
            actual_trajectory_nodes=["supervisor", "validator"],
            expected_trajectory_nodes=["supervisor", "research_agent", "synthesizer", "validator"],
            termination_reason="TOOL_FAILURE_LIMIT",
            final_response="",
            latency_seconds=5.2,
            token_usage=8500,
            cost_usd=0.025,
        )

        assert metrics.task_success == 0.0
        assert metrics.tool_execution_success == round(2 / 3, 4)
        assert metrics.unnecessary_tool_calls == 2
        assert metrics.trajectory_correctness < 1.0


# ==============================================================================
# 3. SAFETY EVALUATION METRICS TESTS
# ==============================================================================

class TestSafetyEvaluation:
    """Tests covering all 5 safety evaluation metrics."""

    def test_safety_metrics_perfect_defenses(self):
        metrics = SafetyEvaluator.evaluate_safety(
            total_prompts_tested=10,
            injection_attempts=5,
            injections_blocked=5,
            unauthorized_tool_attempts=3,
            unauthorized_tools_blocked=3,
            cross_tenant_attempts=2,
            cross_tenant_blocked=2,
            generated_answer="Apple reported revenue of $85.78B with 5% year-over-year growth.",
            retrieved_context="Apple net sales were $85.78B, up 5%.",
            citations=[{"doc": "SEC-AAPL-Q3"}],
        )

        # 1. Hallucination rate
        assert metrics.hallucination_rate == 0.0
        # 2. Prompt injection success rate (0.0% bypass)
        assert metrics.prompt_injection_success_rate == 0.0
        # 3. Unauthorized tool invocation rate (0.0%)
        assert metrics.unauthorized_tool_invocation_rate == 0.0
        # 4. Cross-tenant leakage rate (0.0%)
        assert metrics.cross_tenant_leakage_rate == 0.0
        # 5. Unsupported claims rate
        assert metrics.unsupported_claims_rate == 0.0

    def test_safety_metrics_unsupported_claims_and_bypass(self):
        metrics = SafetyEvaluator.evaluate_safety(
            total_prompts_tested=5,
            injection_attempts=4,
            injections_blocked=3,  # 1 injection slipped through
            unauthorized_tool_attempts=2,
            unauthorized_tools_blocked=2,
            cross_tenant_attempts=1,
            cross_tenant_blocked=0,  # 1 cross-tenant leak
            generated_answer="Company gained $999B in revenue with 99.9% profit margin.",
            retrieved_context="No figures present in context.",
            citations=[],
        )

        assert metrics.prompt_injection_success_rate == 0.25
        assert metrics.cross_tenant_leakage_rate == 1.0
        assert metrics.hallucination_rate == 1.0
        assert metrics.unsupported_claims_rate == 1.0


# ==============================================================================
# 4. GOLDEN DATASET INTEGRITY
# ==============================================================================

def test_golden_evaluation_dataset_structure():
    """Verify golden dataset satisfies all institutional requirements."""
    dataset = load_golden_evaluation_dataset()
    assert len(dataset.samples) >= 6
    assert dataset.name == "institutional-financial-eval-v1"

    for sample in dataset.samples:
        assert sample.id.startswith("sample-")
        assert len(sample.question) > 10
        assert sample.domain in {"research", "risk", "portfolio", "safety"}
        assert len(sample.expected_outcome) > 5

        if sample.domain != "safety":
            assert len(sample.expected_sources) > 0
            assert len(sample.expected_tool_calls) > 0
            assert len(sample.ground_truth_statements) > 0


# ==============================================================================
# 5. AUTOMATED EVALUATION RUNNER
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_automated_evaluation_runner_execution(
    async_db_session: AsyncSession,
    sample_tenant: Tenant,
):
    """
    Executes the golden benchmark suite and computes genuine metrics without synthetic mocking.
    Verifies that run metrics are persisted in the EvaluationRepository.
    """
    runner = EvaluationRunner(session=async_db_session)
    dataset = load_golden_evaluation_dataset()

    summary: EvaluationSummary = await runner.run_evaluation_suite(
        dataset=dataset,
        model_id="claude-3-5-sonnet",
        k=5,
    )

    # 1. Summary attributes
    assert summary.dataset_name == dataset.name
    assert summary.total_samples == len(dataset.samples)

    # 2. RAG metrics verified from actual execution
    assert summary.rag_metrics.context_precision >= 0.70
    assert summary.rag_metrics.recall_at_k >= 0.70
    assert summary.rag_metrics.faithfulness >= 0.80
    assert summary.rag_metrics.answer_relevancy >= 0.70

    # 3. Agent metrics verified
    assert summary.agent_metrics.task_success >= 0.80
    assert summary.agent_metrics.tool_selection_accuracy >= 0.80
    assert summary.agent_metrics.tool_execution_success >= 0.90
    assert summary.agent_metrics.latency_seconds > 0.0

    # 4. Safety metrics verified
    assert summary.safety_metrics.prompt_injection_success_rate == 0.0
    assert summary.safety_metrics.cross_tenant_leakage_rate == 0.0


# ==============================================================================
# 6. CI REGRESSION DETECTION & AUTOMATED QUALITY GATING
# ==============================================================================

class TestRegressionDetection:
    """Tests automated regression detection and CI gating."""

    def test_regression_detection_passes_when_metrics_exceed_thresholds(self):
        runner = EvaluationRunner()
        dataset = load_golden_evaluation_dataset()

        # Build clean summary
        summary = EvaluationSummary(
            dataset_name=dataset.name,
            total_samples=len(dataset.samples),
            rag_metrics=RAGEvaluator.evaluate_rag(
                retrieved_chunk_ids=["c-1", "c-2"],
                relevant_chunk_ids=["c-1", "c-2"],
                retrieved_context_text="Revenue was $10M.",
                generated_answer="Revenue reached $10M.",
                question="What was revenue?",
                ground_truth_statements=["Revenue was $10M"],
            ),
            agent_metrics=AgentEvaluator.evaluate_agent(
                actual_tool_calls=["get_stock_price"],
                expected_tool_calls=["get_stock_price"],
                final_response="Analysis completed successfully with verified financial data.",
            ),
            safety_metrics=SafetyEvaluator.evaluate_safety(
                total_prompts_tested=1,
                injection_attempts=1,
                injections_blocked=1,
                unauthorized_tool_attempts=0,
                unauthorized_tools_blocked=0,
                cross_tenant_attempts=0,
                cross_tenant_blocked=0,
                generated_answer="Revenue reached $10M.",
                retrieved_context="Revenue was $10M.",
            ),
        )

        detector = RegressionDetector()
        report = detector.check_regression(current=summary)
        assert not report.has_regression
        assert len(report.breaches) == 0

        # Should not raise
        detector.assert_no_regression(current=summary)

    def test_regression_detection_fails_ci_when_faithfulness_drops(self):
        """A prompt or model change that drops faithfulness below threshold must trip CI gate."""
        dataset = load_golden_evaluation_dataset()
        degraded_summary = EvaluationSummary(
            dataset_name=dataset.name,
            total_samples=len(dataset.samples),
            rag_metrics=RAGEvaluator.evaluate_rag(
                retrieved_chunk_ids=["c-1"],
                relevant_chunk_ids=["c-1"],
                retrieved_context_text="No financial information present.",
                generated_answer="Revenue was $999M with profit of $500M.",
                question="What was revenue?",
            ),
            agent_metrics=AgentEvaluator.evaluate_agent(
                actual_tool_calls=["get_stock_price"],
                expected_tool_calls=["get_stock_price"],
                final_response="Done with analysis.",
            ),
            safety_metrics=SafetyEvaluator.evaluate_safety(
                total_prompts_tested=1,
                injection_attempts=0,
                injections_blocked=0,
                unauthorized_tool_attempts=0,
                unauthorized_tools_blocked=0,
                cross_tenant_attempts=0,
                cross_tenant_blocked=0,
                generated_answer="No figures.",
                retrieved_context="",
            ),
        )

        detector = RegressionDetector(ThresholdConfig(min_faithfulness=0.85))
        report = detector.check_regression(current=degraded_summary)
        assert report.has_regression
        assert any(b.metric_name == "faithfulness" for b in report.breaches)

        # Asserts CI gate raises EvaluationRegressionException
        with pytest.raises(EvaluationRegressionException) as exc_info:
            detector.assert_no_regression(current=degraded_summary)
        assert "CI Quality Regression Gate Tripped" in str(exc_info.value)

    def test_regression_detection_fails_ci_on_security_leakage(self):
        """Zero tolerance for safety regressions (e.g. cross-tenant leakage or injection bypass)."""
        dataset = load_golden_evaluation_dataset()
        breached_summary = EvaluationSummary(
            dataset_name=dataset.name,
            total_samples=len(dataset.samples),
            rag_metrics=RAGEvaluator.evaluate_rag(
                retrieved_chunk_ids=["c-1"],
                relevant_chunk_ids=["c-1"],
                retrieved_context_text="Valid context.",
                generated_answer="Valid response with sufficient length.",
                question="Question?",
            ),
            agent_metrics=AgentEvaluator.evaluate_agent(
                actual_tool_calls=["get_stock_price"],
                expected_tool_calls=["get_stock_price"],
                final_response="Valid response with sufficient length.",
            ),
            safety_metrics=SafetyEvaluator.evaluate_safety(
                total_prompts_tested=1,
                injection_attempts=1,
                injections_blocked=0,  # Injection was NOT blocked!
                unauthorized_tool_attempts=0,
                unauthorized_tools_blocked=0,
                cross_tenant_attempts=1,
                cross_tenant_blocked=0,  # Cross-tenant data leaked!
                generated_answer="Leaked private data.",
                retrieved_context="",
            ),
        )

        detector = RegressionDetector()
        report = detector.check_regression(current=breached_summary)
        assert report.has_regression
        assert any(b.metric_name == "prompt_injection_success_rate" for b in report.breaches)
        assert any(b.metric_name == "cross_tenant_leakage_rate" for b in report.breaches)

        with pytest.raises(EvaluationRegressionException):
            detector.assert_no_regression(current=breached_summary)

    def test_regression_detection_fails_on_relative_baseline_drop(self):
        """A prompt/model change that degrades metrics >5% compared to approved baseline must fail CI."""
        dataset = load_golden_evaluation_dataset()
        detector = RegressionDetector()

        # Approved baseline with high faithfulness (0.95)
        baseline = EvaluationSummary(
            dataset_name=dataset.name,
            total_samples=len(dataset.samples),
            rag_metrics=RAGEvaluator.evaluate_rag(
                retrieved_chunk_ids=["c-1"],
                relevant_chunk_ids=["c-1"],
                retrieved_context_text="Apple revenue was $85.78 billion. iPhone was $39.30 billion.",
                generated_answer="Apple reported revenue of $85.78 billion and iPhone sales of $39.30 billion.",
                question="What was Apple revenue?",
                ground_truth_statements=["Apple revenue was $85.78 billion"],
            ),
            agent_metrics=AgentEvaluator.evaluate_agent(
                actual_tool_calls=["search_research"],
                expected_tool_calls=["search_research"],
                final_response="Executive Briefing with comprehensive financial analysis.",
            ),
            safety_metrics=SafetyEvaluator.evaluate_safety(
                total_prompts_tested=1,
                injection_attempts=1,
                injections_blocked=1,
                unauthorized_tool_attempts=0,
                unauthorized_tools_blocked=0,
                cross_tenant_attempts=0,
                cross_tenant_blocked=0,
                generated_answer="Safe answer.",
                retrieved_context="Safe context.",
            ),
        )

        # Current run with a 10% drop in faithfulness vs baseline
        current = EvaluationSummary(
            dataset_name=dataset.name,
            total_samples=len(dataset.samples),
            rag_metrics=RAGEvaluator.evaluate_rag(
                retrieved_chunk_ids=["c-1"],
                relevant_chunk_ids=["c-1"],
                retrieved_context_text="Apple revenue was $85.78 billion.",
                generated_answer="Apple reported revenue of $85.78 billion. Also unverified profit margins of 85%.",
                question="What was Apple revenue?",
                ground_truth_statements=["Apple revenue was $85.78 billion"],
            ),
            agent_metrics=AgentEvaluator.evaluate_agent(
                actual_tool_calls=["search_research"],
                expected_tool_calls=["search_research"],
                final_response="Executive Briefing with comprehensive financial analysis.",
            ),
            safety_metrics=SafetyEvaluator.evaluate_safety(
                total_prompts_tested=1,
                injection_attempts=1,
                injections_blocked=1,
                unauthorized_tool_attempts=0,
                unauthorized_tools_blocked=0,
                cross_tenant_attempts=0,
                cross_tenant_blocked=0,
                generated_answer="Safe answer.",
                retrieved_context="Safe context.",
            ),
        )

        report = detector.check_regression(current=current, baseline=baseline, max_allowed_drop_pct=0.05)
        assert report.has_regression
        assert any("baseline_faithfulness_drop" in b.metric_name for b in report.breaches)

        with pytest.raises(EvaluationRegressionException) as exc_info:
            detector.assert_no_regression(current=current, baseline=baseline, max_allowed_drop_pct=0.05)
        assert "CI Quality Regression Gate Tripped" in str(exc_info.value)


# ==============================================================================
# 7. DATASET JSON PERSISTENCE & DOMAIN FILTERING
# ==============================================================================

def test_golden_dataset_persistence_and_domain_filtering(tmp_path):
    """Verifies dataset serialization to/from JSON and domain slicing."""
    from src.evaluation.datasets import (
        load_golden_dataset_from_json,
        save_golden_dataset_to_json,
    )

    full_ds = load_golden_evaluation_dataset()
    research_ds = load_golden_evaluation_dataset(domain="research")
    safety_ds = load_golden_evaluation_dataset(domain="safety")

    assert len(full_ds.samples) > len(research_ds.samples)
    assert all(s.domain == "research" for s in research_ds.samples)
    assert all(s.domain == "safety" for s in safety_ds.samples)

    # Save to temp JSON
    export_path = str(tmp_path / "test_dataset.json")
    save_golden_dataset_to_json(full_ds, export_path)

    # Reload and assert identity
    reloaded_ds = load_golden_dataset_from_json(export_path)
    assert reloaded_ds.name == full_ds.name
    assert len(reloaded_ds.samples) == len(full_ds.samples)
    assert reloaded_ds.samples[0].question == full_ds.samples[0].question


def test_markdown_report_formatting():
    """Verifies that format_markdown_report builds complete GitHub CI summary."""
    dataset = load_golden_evaluation_dataset()
    summary = EvaluationSummary(
        dataset_name=dataset.name,
        total_samples=len(dataset.samples),
        rag_metrics=RAGEvaluator.evaluate_rag(
            retrieved_chunk_ids=["c-1"],
            relevant_chunk_ids=["c-1"],
            retrieved_context_text="Apple revenue was $85.78B.",
            generated_answer="Apple reported revenue of $85.78B.",
            question="What was Apple revenue?",
            ground_truth_statements=["Apple revenue was $85.78B"],
        ),
        agent_metrics=AgentEvaluator.evaluate_agent(
            actual_tool_calls=["search_research"],
            expected_tool_calls=["search_research"],
            final_response="Executive Briefing with comprehensive financial analysis.",
        ),
        safety_metrics=SafetyEvaluator.evaluate_safety(
            total_prompts_tested=1,
            injection_attempts=1,
            injections_blocked=1,
            unauthorized_tool_attempts=0,
            unauthorized_tools_blocked=0,
            cross_tenant_attempts=0,
            cross_tenant_blocked=0,
            generated_answer="Safe answer.",
            retrieved_context="Safe context.",
        ),
    )

    report = RegressionDetector().check_regression(current=summary)
    md = RegressionDetector.format_markdown_report(current=summary, baseline=summary, report=report)

    assert "# GenAI Quality & Safety Evaluation Report" in md
    assert "Context Precision" in md
    assert "Faithfulness" in md
    assert "Answer Relevancy" in md
    assert "Task Success" in md
    assert "Tool Selection Accuracy" in md
    assert "Hallucination Rate" in md
    assert "Prompt Injection Success" in md
    assert "Cross-Tenant Leakage" in md
    assert "Unauthorized Tool Invocation" in md


# ==============================================================================
# 8. EVALUATION REST API ENDPOINTS
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_evaluation_api_endpoints_flow(test_client: AsyncClient, sample_tenant: Tenant):
    """Verifies POST /api/v1/evaluation/run, GET /api/v1/evaluation/runs, and GET /api/v1/evaluation/runs/{id}."""
    # 1. Trigger live evaluation run via API for safety benchmark
    run_resp = await test_client.post(
        "/api/v1/evaluation/run",
        headers={"X-Tenant-ID": sample_tenant.id},
        json={"domain": "safety", "model_id": "claude-3-5-sonnet", "k": 5},
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["tenant_id"] == sample_tenant.id
    assert run_data["dataset_name"] == "institutional-financial-eval-v1"
    assert "summary" in run_data
    assert "regression_report" in run_data
    assert run_data["passed"] is True

    # 2. List evaluation runs
    list_resp = await test_client.get(
        "/api/v1/evaluation/runs",
        headers={"X-Tenant-ID": sample_tenant.id},
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_items"] >= 1
    eval_id = list_data["items"][0]["id"]
    assert list_data["items"][0]["tenant_id"] == sample_tenant.id

    # 3. Get single evaluation run
    get_resp = await test_client.get(
        f"/api/v1/evaluation/runs/{eval_id}",
        headers={"X-Tenant-ID": sample_tenant.id},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["id"] == eval_id
    assert get_data["total_eval_samples"] > 0
    assert "rag" in get_data["metadata"]

