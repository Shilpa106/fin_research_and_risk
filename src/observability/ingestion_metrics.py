import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IngestionMetricsSummary:
    """Snapshot of ingestion pipeline performance and queue metrics."""
    documents_processed_total: int
    documents_failed_total: int
    duplicate_events_skipped_total: int
    active_queue_depth: int
    dlq_depth: int
    avg_latency_ms: float
    p95_latency_ms: float
    throughput_docs_per_minute: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


class IngestionMetricsTracker:
    """
    Thread-safe metrics aggregator for asynchronous document ingestion.
    Tracks latency histograms, error counts, queue depths, and processing throughput.
    """

    def __init__(self, history_size: int = 1000):
        self._lock = threading.Lock()
        self._processed_count = 0
        self._failed_count = 0
        self._duplicate_skipped_count = 0
        self._queue_depth = 0
        self._dlq_depth = 0
        self._latencies: deque[float] = deque(maxlen=history_size)
        self._completion_timestamps: deque[float] = deque(maxlen=history_size)

    def record_document_completed(self, latency_ms: float, tenant_id: str | None = None) -> None:
        """Records a successfully completed document ingestion."""
        with self._lock:
            self._processed_count += 1
            self._latencies.append(latency_ms)
            self._completion_timestamps.append(time.time())

    def record_document_failed(self, reason: str, tenant_id: str | None = None) -> None:
        """Records a failed ingestion event."""
        with self._lock:
            self._failed_count += 1

    def record_duplicate_skipped(self, tenant_id: str | None = None) -> None:
        """Records a duplicate event skipped via idempotency check."""
        with self._lock:
            self._duplicate_skipped_count += 1

    def update_queue_depth(self, depth: int) -> None:
        """Updates current active queue depth gauge."""
        with self._lock:
            self._queue_depth = depth

    def update_dlq_depth(self, depth: int) -> None:
        """Updates Dead-Letter Queue depth gauge."""
        with self._lock:
            self._dlq_depth = depth

    def get_summary(self) -> IngestionMetricsSummary:
        """Calculates current metrics summary."""
        with self._lock:
            now = time.time()
            one_min_ago = now - 60.0

            # Calculate throughput over the last minute
            recent_completed = sum(1 for t in self._completion_timestamps if t >= one_min_ago)
            throughput = float(recent_completed)  # docs per minute

            # Calculate latency percentiles
            if self._latencies:
                sorted_lats = sorted(self._latencies)
                avg_lat = sum(sorted_lats) / len(sorted_lats)
                p95_idx = int(len(sorted_lats) * 0.95)
                p95_lat = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]
            else:
                avg_lat = 0.0
                p95_lat = 0.0

            return IngestionMetricsSummary(
                documents_processed_total=self._processed_count,
                documents_failed_total=self._failed_count,
                duplicate_events_skipped_total=self._duplicate_skipped_count,
                active_queue_depth=self._queue_depth,
                dlq_depth=self._dlq_depth,
                avg_latency_ms=round(avg_lat, 2),
                p95_latency_ms=round(p95_lat, 2),
                throughput_docs_per_minute=throughput,
            )

    def reset(self) -> None:
        """Resets all metrics (primarily for test isolation)."""
        with self._lock:
            self._processed_count = 0
            self._failed_count = 0
            self._duplicate_skipped_count = 0
            self._queue_depth = 0
            self._dlq_depth = 0
            self._latencies.clear()
            self._completion_timestamps.clear()


# Global tracker singleton
metrics_tracker = IngestionMetricsTracker()
