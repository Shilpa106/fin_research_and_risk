import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .metrics import EnterpriseMetricsRegistry, metrics_registry

logger = logging.getLogger("enterprise_copilot.observability.alerting")


class AlertSeverity(str, Enum):
    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"


class AlertStatus(str, Enum):
    OK = "OK"
    FIRING = "FIRING"
    RESOLVED = "RESOLVED"


@dataclass
class AlertRule:
    """Configurable Alert Definition."""
    name: str
    description: str
    severity: AlertSeverity
    condition_fn: Callable[[EnterpriseMetricsRegistry], tuple[bool, float, float]]  # returns (is_triggered, actual, threshold)
    threshold_description: str
    cooldown_seconds: float = 60.0
    last_evaluated: float | None = None
    last_fired: float | None = None


@dataclass
class Alert:
    """Active or Historical Alert Incident."""
    rule_name: str
    severity: AlertSeverity
    status: AlertStatus
    description: str
    actual_value: float
    threshold_value: float
    timestamp: float = field(default_factory=time.time)
    resolved_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "status": self.status.value,
            "description": self.description,
            "actual_value": self.actual_value,
            "threshold_value": self.threshold_value,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)),
            "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.resolved_at)) if self.resolved_at else None,
            "metadata": self.metadata,
        }


class AlertManager:
    """
    Enterprise Observability Alerting Engine.
    Periodically evaluates golden signals and operational thresholds against real-time metrics.
    """

    def __init__(self, metrics: EnterpriseMetricsRegistry | None = None):
        self.metrics = metrics or metrics_registry
        self.rules: list[AlertRule] = []
        self.active_alerts: dict[str, Alert] = {}
        self.alert_history: list[Alert] = []
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        """Configures enterprise standard rules for API, RAG, Agent, LLM, and Infrastructure."""

        # 1. API Error Rate Spike (P1_CRITICAL)
        def _check_api_errors(m: EnterpriseMetricsRegistry) -> tuple[bool, float, float]:
            api_m = m.get_api_metrics()
            err_rate = api_m["error_rate"]
            threshold = 0.01  # > 1%
            # Only trigger if at least 10 requests processed
            is_firing = bool(api_m["total_requests"] >= 10 and err_rate > threshold)
            return is_firing, err_rate, threshold

        self.rules.append(
            AlertRule(
                name="API_ERROR_RATE_SPIKE",
                description="HTTP 5xx / 4xx error rate exceeded 1.0% threshold",
                severity=AlertSeverity.P1_CRITICAL,
                condition_fn=_check_api_errors,
                threshold_description="error_rate > 0.01 (1.0%)",
            )
        )

        # 2. P99 API Latency Degradation (P2_HIGH)
        def _check_p99_latency(m: EnterpriseMetricsRegistry) -> tuple[bool, float, float]:
            api_m = m.get_api_metrics()
            p99_ms = api_m["p99_latency_ms"]
            threshold = 2000.0  # 2000 ms SLA
            is_firing = bool(api_m["total_requests"] >= 5 and p99_ms > threshold)
            return is_firing, p99_ms, threshold

        self.rules.append(
            AlertRule(
                name="API_P99_LATENCY_DEGRADATION",
                description="API P99 latency degraded beyond 2000ms SLA",
                severity=AlertSeverity.P2_HIGH,
                condition_fn=_check_p99_latency,
                threshold_description="p99_latency_ms > 2000ms",
            )
        )

        # 3. OpenSearch Cluster Latency Spike (P1_CRITICAL)
        def _check_opensearch(m: EnterpriseMetricsRegistry) -> tuple[bool, float, float]:
            infra_m = m.get_infrastructure_metrics()
            os_latency = infra_m["opensearch_latency_ms"]["p95"]
            threshold = 1000.0  # > 1000ms
            is_firing = bool(os_latency > threshold)
            return is_firing, os_latency, threshold

        self.rules.append(
            AlertRule(
                name="OPENSEARCH_LATENCY_SPIKE",
                description="OpenSearch hybrid vector retrieval P95 latency exceeded 1000ms",
                severity=AlertSeverity.P1_CRITICAL,
                condition_fn=_check_opensearch,
                threshold_description="opensearch_p95_ms > 1000ms",
            )
        )

        # 4. Multi-Agent Failure Rate Spike (P2_HIGH)
        def _check_agent_failure(m: EnterpriseMetricsRegistry) -> tuple[bool, float, float]:
            ag_m = m.get_agent_metrics()
            fail_rate = ag_m["failure_rate"]
            threshold = 0.15  # > 15%
            is_firing = bool(ag_m["total_completed_workflows"] >= 5 and fail_rate > threshold)
            return is_firing, fail_rate, threshold

        self.rules.append(
            AlertRule(
                name="AGENT_FAILURE_RATE_SPIKE",
                description="Multi-agent orchestration workflow failure rate exceeded 15%",
                severity=AlertSeverity.P2_HIGH,
                condition_fn=_check_agent_failure,
                threshold_description="agent_failure_rate > 0.15",
            )
        )

        # 5. Queue Depth Backlog (P3_MEDIUM)
        def _check_queue_depth(m: EnterpriseMetricsRegistry) -> tuple[bool, float, float]:
            infra_m = m.get_infrastructure_metrics()
            q_depth = float(infra_m["queue_depth"])
            threshold = 50.0  # > 50 tasks
            is_firing = bool(q_depth > threshold)
            return is_firing, q_depth, threshold

        self.rules.append(
            AlertRule(
                name="QUEUE_DEPTH_BACKLOG",
                description="Pending tasks or HITL review queue backlog exceeded 50 items",
                severity=AlertSeverity.P3_MEDIUM,
                condition_fn=_check_queue_depth,
                threshold_description="queue_depth > 50",
            )
        )

        # 6. High System Memory Pressure (P2_HIGH)
        def _check_memory_pressure(m: EnterpriseMetricsRegistry) -> tuple[bool, float, float]:
            infra_m = m.get_infrastructure_metrics()
            mem_pct = infra_m["memory"]["percent"]
            threshold = 90.0  # > 90%
            is_firing = bool(mem_pct > threshold)
            return is_firing, mem_pct, threshold

        self.rules.append(
            AlertRule(
                name="HIGH_MEMORY_PRESSURE",
                description="System host memory utilization exceeded 90%",
                severity=AlertSeverity.P2_HIGH,
                condition_fn=_check_memory_pressure,
                threshold_description="memory_percent > 90.0%",
            )
        )

    def evaluate(self) -> list[Alert]:
        """
        Executes an evaluation cycle across all registered alert rules.
        Manages transition states (OK -> FIRING -> RESOLVED) and dispatches notifications.
        """
        now = time.time()
        newly_fired: list[Alert] = []

        for rule in self.rules:
            rule.last_evaluated = now
            try:
                is_triggered, actual, threshold = rule.condition_fn(self.metrics)
            except Exception as e:
                logger.error(f"Error evaluating alert rule {rule.name}: {e}")
                continue

            existing_alert = self.active_alerts.get(rule.name)

            if is_triggered:
                if not existing_alert:
                    # New Alert Firing
                    alert = Alert(
                        rule_name=rule.name,
                        severity=rule.severity,
                        status=AlertStatus.FIRING,
                        description=rule.description,
                        actual_value=round(actual, 4),
                        threshold_value=round(threshold, 4),
                        timestamp=now,
                        metadata={"threshold_rule": rule.threshold_description},
                    )
                    self.active_alerts[rule.name] = alert
                    self.alert_history.append(alert)
                    newly_fired.append(alert)
                    rule.last_fired = now
                    self._dispatch_alert(alert)
            else:
                if existing_alert and existing_alert.status == AlertStatus.FIRING:
                    # Alert Resolved
                    existing_alert.status = AlertStatus.RESOLVED
                    existing_alert.resolved_at = now
                    del self.active_alerts[rule.name]
                    logger.info(f"Alert RESOLVED: {rule.name}")

        return newly_fired

    def _dispatch_alert(self, alert: Alert) -> None:
        """Dispatches alert notification to logger and downstream channels."""
        logger.warning(
            f"🚨 ALERT [{alert.severity.value}] {alert.rule_name} FIRING! "
            f"Description: {alert.description} | Value: {alert.actual_value} (Threshold: {alert.threshold_value})"
        )

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Returns JSON-compatible list of currently active firing alerts."""
        return [alert.to_dict() for alert in self.active_alerts.values()]

    def get_alert_history(self) -> list[dict[str, Any]]:
        """Returns list of past and present alert events."""
        return [alert.to_dict() for alert in self.alert_history]


# Global Alert Manager Singleton
alert_manager = AlertManager()
