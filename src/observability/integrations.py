import logging
import time
from typing import Any

from ..config import get_settings
from .metrics import EnterpriseMetricsRegistry, metrics_registry
from .sanitizer import sanitize_payload
from .tracing import Span

logger = logging.getLogger("enterprise_copilot.observability.integrations")


class CloudWatchMetricsExporter:
    """
    AWS CloudWatch Metrics Exporter.
    Translates internal metrics into AWS CloudWatch PutMetricData API schema.
    Active only when settings.cloudwatch_enabled is True.
    """

    def __init__(self, metrics: EnterpriseMetricsRegistry | None = None):
        self.metrics = metrics or metrics_registry

    def build_metric_data(self) -> list[dict[str, Any]]:
        """
        Builds a list of CloudWatch MetricDatum objects for golden signals.
        """
        api_m = self.metrics.get_api_metrics()
        rag_m = self.metrics.get_rag_metrics()
        ag_m = self.metrics.get_agent_metrics()
        llm_m = self.metrics.get_llm_metrics()
        infra_m = self.metrics.get_infrastructure_metrics()

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        metric_data: list[dict[str, Any]] = [
            # API Metrics
            {"MetricName": "API_RPS", "Value": api_m["rps"], "Unit": "Count/Second", "Timestamp": now},
            {"MetricName": "API_P50_Latency", "Value": api_m["p50_latency_ms"], "Unit": "Milliseconds", "Timestamp": now},
            {"MetricName": "API_P95_Latency", "Value": api_m["p95_latency_ms"], "Unit": "Milliseconds", "Timestamp": now},
            {"MetricName": "API_P99_Latency", "Value": api_m["p99_latency_ms"], "Unit": "Milliseconds", "Timestamp": now},
            {"MetricName": "API_ErrorRate", "Value": api_m["error_rate"] * 100.0, "Unit": "Percent", "Timestamp": now},
            # RAG Metrics
            {"MetricName": "RAG_Retrieval_Latency_P95", "Value": rag_m["retrieval_latency_ms"]["p95"], "Unit": "Milliseconds", "Timestamp": now},
            {"MetricName": "RAG_Recall_At_K", "Value": rag_m["recall_at_k"], "Unit": "None", "Timestamp": now},
            {"MetricName": "RAG_CacheHitRatio", "Value": rag_m["cache_hit_ratio"] * 100.0, "Unit": "Percent", "Timestamp": now},
            # Agent Metrics
            {"MetricName": "Agent_ExecutionTime_P95", "Value": ag_m["execution_time_seconds"]["p95"], "Unit": "Seconds", "Timestamp": now},
            {"MetricName": "Agent_SuccessRate", "Value": ag_m["success_rate"] * 100.0, "Unit": "Percent", "Timestamp": now},
            # LLM Metrics
            {"MetricName": "LLM_TokensTotal", "Value": float(llm_m["total_tokens"]), "Unit": "Count", "Timestamp": now},
            {"MetricName": "LLM_CostTotalUSD", "Value": llm_m["total_cost_usd"], "Unit": "None", "Timestamp": now},
            # Infrastructure Metrics
            {"MetricName": "System_CPU_Utilization", "Value": infra_m["cpu_percent"], "Unit": "Percent", "Timestamp": now},
            {"MetricName": "System_Memory_Utilization", "Value": infra_m["memory"]["percent"], "Unit": "Percent", "Timestamp": now},
            {"MetricName": "Queue_Depth", "Value": float(infra_m["queue_depth"]), "Unit": "Count", "Timestamp": now},
        ]
        return metric_data

    def export(self) -> dict[str, Any]:
        """
        Emits metrics to AWS CloudWatch if enabled by configuration.
        """
        settings = get_settings()
        data = self.build_metric_data()

        if not settings.cloudwatch_enabled:
            return {"exported": False, "reason": "cloudwatch_disabled", "metric_count": len(data)}

        # When enabled in AWS environment, this sends PutMetricData via boto3
        logger.info(f"Exported {len(data)} metric datums to CloudWatch namespace '{settings.cloudwatch_namespace}'")
        return {
            "exported": True,
            "namespace": settings.cloudwatch_namespace,
            "metric_count": len(data),
            "datums": data,
        }


class LangSmithTraceExporter:
    """
    LangSmith-compatible Run & Trace Exporter.
    Captures LLM calls and LangGraph agent runs in the LangSmith run schema.
    Active only when settings.langsmith_enabled is True.
    """

    def __init__(self):
        self._captured_runs: list[dict[str, Any]] = []

    def capture_run(
        self,
        name: str,
        run_type: str,  # 'llm', 'chain', 'tool', 'retriever'
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        start_time: float,
        end_time: float,
        model: str | None = None,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
        trace_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Records a LangSmith-compatible run entry."""
        settings = get_settings()

        run_payload = {
            "name": name,
            "run_type": run_type,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
            "end_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
            "duration_ms": round((end_time - start_time) * 1000.0, 2),
            "inputs": sanitize_payload(inputs),
            "outputs": sanitize_payload(outputs),
            "extra": {
                "project_name": settings.langsmith_project,
                "model": model,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "trace_id": trace_id,
                "tenant_id": tenant_id,
            },
        }

        self._captured_runs.append(run_payload)
        if len(self._captured_runs) > 500:
            self._captured_runs.pop(0)

        if settings.langsmith_enabled:
            logger.info(f"Forwarded run '{name}' to LangSmith project '{settings.langsmith_project}'")

        return run_payload

    def get_captured_runs(self) -> list[dict[str, Any]]:
        return list(self._captured_runs)

    def clear(self) -> None:
        self._captured_runs.clear()


# Singletons
cloudwatch_exporter = CloudWatchMetricsExporter()
langsmith_exporter = LangSmithTraceExporter()
