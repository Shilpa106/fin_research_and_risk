from typing import Any


class SimpleMetricsRegistry:
    """
    Lightweight in-memory Prometheus-compatible metrics registry.
    Ensures zero mandatory external telemetry dependencies during unit tests and local runs.
    """

    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.total_duration_seconds = 0.0
        self.active_requests = 0

    def record_request(self, duration: float, is_error: bool = False):
        self.request_count += 1
        self.total_duration_seconds += duration
        if is_error:
            self.error_count += 1

    def get_metrics_summary(self) -> dict[str, Any]:
        avg_latency = (self.total_duration_seconds / self.request_count) if self.request_count > 0 else 0.0
        return {
            "http_requests_total": self.request_count,
            "http_errors_total": self.error_count,
            "http_avg_duration_seconds": round(avg_latency, 4),
            "http_active_requests": self.active_requests,
        }


metrics_registry = SimpleMetricsRegistry()
