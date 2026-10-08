from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ....observability.alerting import alert_manager
from ....observability.infrastructure import infra_collector
from ....observability.integrations import cloudwatch_exporter, langsmith_exporter
from ....observability.metrics import metrics_registry
from ....observability.tracing import default_tracer
from ....security.context import RequestSecurityContext
from ....security.guards import require_permissions

router = APIRouter(prefix="/observability", tags=["Enterprise Observability & Telemetry"])


class AlertEvaluationResponse(BaseModel):
    triggered_count: int
    active_alerts: list[dict[str, Any]]
    history_count: int


@router.get("/metrics/summary", summary="Complete Categorized Platform Metrics")
async def get_metrics_summary(
    context: RequestSecurityContext = Depends(require_permissions("observability:read")),
):
    """
    Returns full metrics telemetry across API, RAG, Multi-Agent, LLM, and Infrastructure pillars.
    """
    # Ensure infrastructure metrics are freshly updated
    await infra_collector.collect_and_record_all()
    return metrics_registry.get_metrics_summary()


@router.get("/alerts", summary="Get Active and Historical System Alerts")
async def get_alerts(
    context: RequestSecurityContext = Depends(require_permissions("observability:read")),
):
    """
    Lists currently active firing alerts and historical alerts.
    """
    return {
        "active_alerts": alert_manager.get_active_alerts(),
        "alert_history": alert_manager.get_alert_history(),
    }


@router.post("/alerts/evaluate", response_model=AlertEvaluationResponse, summary="Trigger Alert Evaluation Cycle")
async def evaluate_alerts(
    context: RequestSecurityContext = Depends(require_permissions("observability:manage")),
):
    """
    Forces an immediate evaluation cycle across all configured alert rules.
    """
    newly_fired = alert_manager.evaluate()
    return AlertEvaluationResponse(
        triggered_count=len(newly_fired),
        active_alerts=alert_manager.get_active_alerts(),
        history_count=len(alert_manager.alert_history),
    )


@router.get("/traces", summary="Get Recent Distributed Trace Spans")
async def get_traces(
    context: RequestSecurityContext = Depends(require_permissions("observability:read")),
):
    """
    Returns finished OpenTelemetry distributed trace spans currently held in buffer.
    """
    finished_spans = default_tracer.get_finished_spans()
    return {
        "span_count": len(finished_spans),
        "spans": [span.to_dict() for span in finished_spans[-50:]],
    }


@router.get("/cloudwatch/preview", summary="Preview AWS CloudWatch PutMetricData Payloads")
async def preview_cloudwatch_metrics(
    context: RequestSecurityContext = Depends(require_permissions("observability:read")),
):
    """
    Previews AWS CloudWatch PutMetricData formatted telemetry.
    """
    return cloudwatch_exporter.export()


@router.get("/langsmith/runs", summary="Get LangSmith Run Captures")
async def get_langsmith_runs(
    context: RequestSecurityContext = Depends(require_permissions("observability:read")),
):
    """
    Retrieves LangSmith-compatible LLM and agent runs captured during execution.
    """
    return {
        "run_count": len(langsmith_exporter.get_captured_runs()),
        "runs": langsmith_exporter.get_captured_runs()[-50:],
    }
