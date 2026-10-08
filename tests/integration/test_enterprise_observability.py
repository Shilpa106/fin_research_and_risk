import json
import logging
import time
import pytest
from httpx import AsyncClient

from src.ai_gateway.gateway import AIGateway
from src.ai_gateway.models import LLMRequest, ModelTaskType, TaskComplexity
from src.domain.entities import Tenant
from src.observability import (
    AlertSeverity,
    AlertStatus,
    StructuredJsonFormatter,
    alert_manager,
    clear_observability_context,
    cloudwatch_exporter,
    default_tracer,
    format_w3c_traceparent,
    generate_trace_id,
    get_observability_context,
    infra_collector,
    langsmith_exporter,
    metrics_registry,
    parse_w3c_traceparent,
    sanitize_payload,
    sanitize_text,
    set_observability_context,
    trace_span,
)
from src.rag.retrieval_service import RetrievalService


# ==============================================================================
# 1. CONTEXT PROPAGATION TESTS (All 6 Required Fields + W3C)
# ==============================================================================

class TestContextPropagation:
    """Verifies request_id, trace_id, tenant_id, user_id, conversation_id, agent_run_id."""

    def test_observability_context_manual_and_w3c_formatting(self):
        ctx = set_observability_context(
            request_id="req-inst-001",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            tenant_id="tenant-goldman-sachs",
            user_id="user-analyst-88",
            conversation_id="conv-thread-99",
            agent_run_id="run-step-42",
        )

        assert ctx.request_id == "req-inst-001"
        assert ctx.correlation_id == "req-inst-001"
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.tenant_id == "tenant-goldman-sachs"
        assert ctx.user_id == "user-analyst-88"
        assert ctx.conversation_id == "conv-thread-99"
        assert ctx.agent_run_id == "run-step-42"

        # Check retrieval from task context
        retrieved_ctx = get_observability_context()
        assert retrieved_ctx.request_id == "req-inst-001"
        assert retrieved_ctx.tenant_id == "tenant-goldman-sachs"

        # Check W3C header generation and parsing
        w3c_header = ctx.to_w3c_header()
        assert w3c_header.startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")
        parsed = parse_w3c_traceparent(w3c_header)
        assert parsed is not None
        trace_id, parent_id, flags = parsed
        assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert flags == "01"

        clear_observability_context()
        assert get_observability_context().tenant_id is None

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_api_middleware_propagates_all_lineage_headers(self, test_client: AsyncClient):
        custom_req_id = "req-custom-abc-123"
        custom_trace = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        custom_tenant = "tenant-morgan-stanley"
        custom_user = "user-pm-10"
        custom_conv = "thread-aapl-deepdive"
        custom_agent_run = "agent-orchestrator-run-007"

        response = await test_client.get(
            "/health",
            headers={
                "X-Request-ID": custom_req_id,
                "traceparent": custom_trace,
                "X-Tenant-ID": custom_tenant,
                "X-User-ID": custom_user,
                "X-Conversation-ID": custom_conv,
                "X-Agent-Run-ID": custom_agent_run,
            },
        )

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == custom_req_id
        assert response.headers.get("X-Correlation-ID") == custom_req_id
        assert response.headers.get("X-Trace-ID") == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert "traceparent" in response.headers
        assert "4bf92f3577b34da6a3ce929d0e0e4736" in response.headers.get("traceparent")


# ==============================================================================
# 2. ZERO-LEAKAGE SECURITY & PRIVACY SANITIZATION
# ==============================================================================

class TestSecurityScrubbing:
    """Verifies that secrets, credentials, and sensitive financial information are never logged."""

    def test_sanitize_text_redacts_credentials_and_pan_and_ssn(self):
        # 1. Bearer and JWT Token
        dirty_auth = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.fake_sig"
        clean_auth = sanitize_text(dirty_auth)
        assert "[REDACTED_BEARER_TOKEN]" in clean_auth
        assert "fake_sig" not in clean_auth

        # 2. AWS Secret Access Key
        dirty_aws = "Connecting using AKIA1234567890ABCDEF and secret_key='supersecretpassword'"
        clean_aws = sanitize_text(dirty_aws)
        assert "[REDACTED_AWS_KEY]" in clean_aws
        assert "[REDACTED_SECRET]" in clean_aws
        assert "supersecretpassword" not in clean_aws

        # 3. Sensitive Financial Info (Credit Card / PAN: 16 digits)
        dirty_pan = "Customer card number 4111-2222-3333-4444 charged $500"
        clean_pan = sanitize_text(dirty_pan)
        assert "[REDACTED_PAN]" in clean_pan
        assert "4111-2222-3333-4444" not in clean_pan

        # 4. Sensitive PII (Social Security Number)
        dirty_ssn = "Taxpayer SSN is 123-45-6789 for filing 10-K"
        clean_ssn = sanitize_text(dirty_ssn)
        assert "[REDACTED_SSN]" in clean_ssn
        assert "123-45-6789" not in clean_ssn

    def test_structured_json_formatter_never_leaks_secrets(self):
        formatter = StructuredJsonFormatter(service_name="test-security-service")
        set_observability_context(
            request_id="req-sec-99",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            tenant_id="tenant-hedgefund",
            user_id="trader-01",
            conversation_id="conv-alpha",
            agent_run_id="run-quant-1",
        )

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test_sec.py",
            lineno=50,
            msg="User api_key='sk-live-secret-key-12345' submitted credit card 5555 4444 3333 2222",
            args=(),
            exc_info=None,
        )
        record.extra_fields = {
            "password": "plain_text_password!",
            "portfolio_value": 5000000.0,
            "pan": "4000-1234-5678-9010",
        }

        output = formatter.format(record)
        log_json = json.loads(output)

        # Context Lineage Present
        assert log_json["request_id"] == "req-sec-99"
        assert log_json["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert log_json["tenant_id"] == "tenant-hedgefund"
        assert log_json["user_id"] == "trader-01"
        assert log_json["conversation_id"] == "conv-alpha"
        assert log_json["agent_run_id"] == "run-quant-1"

        # Sensitive data redacted
        assert "sk-live-secret-key-12345" not in output
        assert "plain_text_password!" not in output
        assert "5555 4444 3333 2222" not in output
        assert log_json["password"] == "[REDACTED_CREDENTIAL]"
        assert log_json["pan"] == "[REDACTED_CREDENTIAL]"
        assert log_json["portfolio_value"] == 5000000.0

        clear_observability_context()


# ==============================================================================
# 3. METRICS TESTS (API, RAG, AGENT, LLM, INFRASTRUCTURE)
# ==============================================================================

class TestEnterpriseMetricsTracking:
    """Verifies telemetry across all 5 operational pillars."""

    def test_api_metrics_golden_signals(self):
        # Record synthetic burst
        metrics_registry.record_api_request("/api/v1/copilot/chat", "POST", 200, 0.050, "tenant-1")
        metrics_registry.record_api_request("/api/v1/copilot/chat", "POST", 200, 0.120, "tenant-1")
        metrics_registry.record_api_request("/api/v1/copilot/chat", "POST", 200, 0.250, "tenant-1")
        metrics_registry.record_api_request("/api/v1/copilot/chat", "POST", 500, 0.800, "tenant-1")

        api_m = metrics_registry.get_api_metrics()
        assert api_m["rps"] >= 0.0
        assert api_m["p50_latency_ms"] > 0
        assert api_m["p95_latency_ms"] > api_m["p50_latency_ms"]
        assert api_m["p99_latency_ms"] >= api_m["p95_latency_ms"]
        assert api_m["error_rate"] > 0.0  # 1 error out of 4 = 0.25
        assert api_m["total_requests"] >= 4

    def test_rag_metrics_telemetry(self):
        metrics_registry.record_rag_retrieval(
            retrieval_latency_seconds=0.035,
            reranker_latency_seconds=0.015,
            recall_at_k=0.92,
            cache_hit=True,
        )
        metrics_registry.record_rag_retrieval(
            retrieval_latency_seconds=0.040,
            reranker_latency_seconds=0.020,
            recall_at_k=0.88,
            cache_hit=False,
        )

        rag_m = metrics_registry.get_rag_metrics()
        assert rag_m["retrieval_latency_ms"]["p50"] > 0
        assert rag_m["reranker_latency_ms"]["p50"] > 0
        assert rag_m["recall_at_k"] >= 0.85
        assert 0.0 <= rag_m["cache_hit_ratio"] <= 1.0

    def test_agent_metrics_telemetry(self):
        metrics_registry.record_agent_execution(
            duration_seconds=1.25,
            iterations=3,
            tool_calls_count=4,
            is_success=True,
            tenant_id="tenant-1",
        )
        metrics_registry.record_agent_execution(
            duration_seconds=2.10,
            iterations=5,
            tool_calls_count=6,
            is_success=False,
            tenant_id="tenant-1",
        )

        ag_m = metrics_registry.get_agent_metrics()
        assert ag_m["execution_time_seconds"]["avg"] > 0
        assert ag_m["iterations"]["avg"] > 0
        assert ag_m["total_tool_calls"] >= 10
        assert 0.0 <= ag_m["success_rate"] <= 1.0
        assert 0.0 <= ag_m["failure_rate"] <= 1.0

    def test_llm_metrics_telemetry(self):
        metrics_registry.record_llm_call(
            model="anthropic.claude-3-5-sonnet",
            provider="bedrock",
            input_tokens=1500,
            output_tokens=400,
            duration_seconds=0.450,
            cost_usd=0.0105,
        )

        llm_m = metrics_registry.get_llm_metrics()
        assert llm_m["total_requests"] >= 1
        assert llm_m["input_tokens"] >= 1500
        assert llm_m["output_tokens"] >= 400
        assert llm_m["total_tokens"] >= 1900
        assert llm_m["latency_ms"]["p50"] > 0
        assert llm_m["total_cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_infrastructure_collector_telemetry(self):
        res = await infra_collector.collect_and_record_all(queue_depth=5)
        infra_m = metrics_registry.get_infrastructure_metrics()

        assert infra_m["cpu_percent"] > 0
        assert infra_m["memory"]["total_bytes"] > 0
        assert infra_m["memory"]["used_bytes"] > 0
        assert infra_m["memory"]["percent"] > 0
        assert infra_m["queue_depth"] == 5
        assert infra_m["database_connections"]["pool_size"] >= 1
        assert "opensearch_latency_ms" in infra_m

    def test_prometheus_exposition_generation(self):
        exposition = metrics_registry.generate_prometheus_exposition()
        assert "# HELP http_requests_total" in exposition
        assert "# TYPE http_requests_total counter" in exposition
        assert "http_rps" in exposition
        assert "http_p50_latency_ms" in exposition
        assert "http_p95_latency_ms" in exposition
        assert "http_p99_latency_ms" in exposition
        assert "rag_retrieval_latency_p95_ms" in exposition
        assert "agent_execution_time_p95_seconds" in exposition
        assert "llm_requests_total" in exposition
        assert "system_cpu_percent" in exposition


# ==============================================================================
# 4. OPENTELEMETRY DISTRIBUTED TRACING
# ==============================================================================

class TestDistributedTracing:
    """Verifies OpenTelemetry tracer, spans, parent-child links, and decorators."""

    def test_tracer_span_lifecycle_and_attributes(self):
        default_tracer.clear()

        with default_tracer.start_as_current_span(
            "parent.transaction",
            attributes={"tenant.id": "tenant-fund-1", "trade.id": "tr-9988"},
        ) as parent_span:
            parent_span.add_event("validation_started")

            with default_tracer.start_as_current_span(
                "child.risk_calculation",
                attributes={"model.type": "historical_var"},
            ) as child_span:
                child_span.set_attribute("confidence", 0.99)

        finished = default_tracer.get_finished_spans()
        assert len(finished) == 2

        child = next(s for s in finished if s.name == "child.risk_calculation")
        parent = next(s for s in finished if s.name == "parent.transaction")

        assert child.duration_ms >= 0.0
        assert parent.duration_ms >= 0.0
        assert child.context.parent_span_id == parent.context.span_id
        assert child.context.trace_id == parent.context.trace_id
        assert child.status == "OK"

    @pytest.mark.asyncio
    async def test_trace_span_decorator(self):
        default_tracer.clear()

        @trace_span("sample.async_subagent_task", attributes={"agent.type": "risk_analyst"})
        async def mock_subagent_task(multiplier: int) -> int:
            return multiplier * 10

        res = await mock_subagent_task(5)
        assert res == 50

        spans = default_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "sample.async_subagent_task"
        assert spans[0].attributes["agent.type"] == "risk_analyst"
        assert spans[0].attributes["code.function"] == "mock_subagent_task"


# ==============================================================================
# 5. ENTERPRISE ALERTING ENGINE
# ==============================================================================

class TestObservabilityAlerting:
    """Verifies threshold-based alerting engine, state transitions, and evaluation."""

    def test_alerting_rule_evaluation_and_firing(self):
        # 1. Trigger High Memory Pressure
        metrics_registry.system_memory_percent.set(95.0)  # > 90% threshold
        fired = alert_manager.evaluate()

        assert any(a.rule_name == "HIGH_MEMORY_PRESSURE" for a in fired)
        active = alert_manager.get_active_alerts()
        assert any(a["rule_name"] == "HIGH_MEMORY_PRESSURE" and a["status"] == "FIRING" for a in active)

        # 2. Resolve High Memory Pressure
        metrics_registry.system_memory_percent.set(65.0)  # Below threshold
        alert_manager.evaluate()

        active_after = alert_manager.get_active_alerts()
        assert not any(a["rule_name"] == "HIGH_MEMORY_PRESSURE" for a in active_after)


# ==============================================================================
# 6. CLOUDWATCH & LANGSMITH INTEGRATIONS
# ==============================================================================

class TestObservabilityIntegrations:
    """Verifies CloudWatch metrics translation and LangSmith run tracking."""

    def test_cloudwatch_metrics_exporter(self):
        datums = cloudwatch_exporter.build_metric_data()
        assert len(datums) >= 10
        metric_names = [d["MetricName"] for d in datums]
        assert "API_RPS" in metric_names
        assert "API_P50_Latency" in metric_names
        assert "API_P95_Latency" in metric_names
        assert "API_P99_Latency" in metric_names
        assert "API_ErrorRate" in metric_names
        assert "RAG_Retrieval_Latency_P95" in metric_names
        assert "Agent_ExecutionTime_P95" in metric_names
        assert "LLM_TokensTotal" in metric_names
        assert "System_CPU_Utilization" in metric_names

    def test_langsmith_trace_exporter(self):
        langsmith_exporter.clear()
        run = langsmith_exporter.capture_run(
            name="llm.bedrock.claude-3-5-sonnet",
            run_type="llm",
            inputs={"query": "Calculate portfolio beta vs SPY"},
            outputs={"result": "Beta is 1.15"},
            start_time=time.time() - 0.250,
            end_time=time.time(),
            model="claude-3-5-sonnet",
            total_tokens=450,
            cost_usd=0.003,
            tenant_id="tenant-citadel",
        )
        assert run["name"] == "llm.bedrock.claude-3-5-sonnet"
        assert run["extra"]["total_tokens"] == 450
        assert len(langsmith_exporter.get_captured_runs()) == 1


# ==============================================================================
# 7. OBSERVABILITY REST API ENDPOINTS
# ==============================================================================

class TestObservabilityAPI:
    """Verifies /health/deep, /metrics, and /api/v1/observability/* endpoints."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_deep_health_and_metrics_endpoints(self, test_client: AsyncClient):
        # 1. /health/deep
        deep_resp = await test_client.get("/health/deep")
        assert deep_resp.status_code in [200, 503]
        deep_data = deep_resp.json()
        assert "status" in deep_data
        assert "components" in deep_data
        assert "database" in deep_data["components"]
        assert "metrics_summary" in deep_data

        # 2. /metrics (Prometheus text format)
        prom_resp = await test_client.get("/metrics")
        assert prom_resp.status_code == 200
        assert "text/plain" in prom_resp.headers.get("content-type", "")
        assert "http_requests_total" in prom_resp.text

        # 3. /metrics?format=json
        json_resp = await test_client.get("/metrics?format=json")
        assert json_resp.status_code == 200
        metrics_json = json_resp.json()
        assert "api" in metrics_json
        assert "rag" in metrics_json
        assert "agent" in metrics_json
        assert "llm" in metrics_json
        assert "infrastructure" in metrics_json

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_observability_api_endpoints_flow(self, test_client: AsyncClient, sample_tenant: Tenant):
        headers = {"X-Tenant-ID": sample_tenant.id}

        # 1. GET /api/v1/observability/metrics/summary
        sum_resp = await test_client.get("/api/v1/observability/metrics/summary", headers=headers)
        assert sum_resp.status_code == 200
        data = sum_resp.json()
        assert "api" in data
        assert "rps" in data["api"]
        assert "p50_latency_ms" in data["api"]

        # 2. GET /api/v1/observability/alerts
        alerts_resp = await test_client.get("/api/v1/observability/alerts", headers=headers)
        assert alerts_resp.status_code == 200
        alerts_data = alerts_resp.json()
        assert "active_alerts" in alerts_data
        assert "alert_history" in alerts_data

        # 3. POST /api/v1/observability/alerts/evaluate
        eval_resp = await test_client.post("/api/v1/observability/alerts/evaluate", headers=headers)
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        assert "triggered_count" in eval_data

        # 4. GET /api/v1/observability/traces
        traces_resp = await test_client.get("/api/v1/observability/traces", headers=headers)
        assert traces_resp.status_code == 200
        assert "spans" in traces_resp.json()

        # 5. GET /api/v1/observability/cloudwatch/preview
        cw_resp = await test_client.get("/api/v1/observability/cloudwatch/preview", headers=headers)
        assert cw_resp.status_code == 200
        assert "metric_count" in cw_resp.json()

        # 6. GET /api/v1/observability/langsmith/runs
        ls_resp = await test_client.get("/api/v1/observability/langsmith/runs", headers=headers)
        assert ls_resp.status_code == 200
        assert "runs" in ls_resp.json()
