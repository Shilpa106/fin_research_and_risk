import math
import threading
import time
from collections import defaultdict
from typing import Any


class Counter:
    """Monotonically increasing counter with multi-dimensional label support."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._values[key] += value

    def get(self, labels: dict[str, str] | None = None) -> float:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def get_all(self) -> dict[tuple[tuple[str, str], ...], float]:
        with self._lock:
            return dict(self._values)

    def total(self) -> float:
        with self._lock:
            return sum(self._values.values())


class Gauge:
    """Instantaneous numerical value gauge."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._values[key] = float(value)

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._values[key] += value

    def dec(self, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._values[key] -= value

    def get(self, labels: dict[str, str] | None = None) -> float:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def get_all(self) -> dict[tuple[tuple[str, str], ...], float]:
        with self._lock:
            return dict(self._values)


class Histogram:
    """
    Distribution tracking histogram with rolling reservoir for P50, P90, P95, P99 percentile calculations.
    """

    def __init__(self, name: str, description: str, reservoir_size: int = 1000):
        self.name = name
        self.description = description
        self.reservoir_size = reservoir_size
        self._lock = threading.Lock()
        self._samples: dict[tuple[tuple[str, str], ...], list[float]] = defaultdict(list)
        self._counts: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)
        self._sums: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._counts[key] += 1
            self._sums[key] += value
            reservoir = self._samples[key]
            reservoir.append(value)
            if len(reservoir) > self.reservoir_size:
                reservoir.pop(0)

    def get_quantiles(self, labels: dict[str, str] | None = None) -> dict[str, float]:
        """Calculates P50, P90, P95, P99 quantiles."""
        with self._lock:
            if labels is not None:
                key = tuple(sorted(labels.items()))
                samples = sorted(self._samples.get(key, []))
            else:
                all_s = []
                for s_list in self._samples.values():
                    all_s.extend(s_list)
                samples = sorted(all_s)

        if not samples:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "count": 0}

        def _quantile(q: float) -> float:
            idx = int(math.ceil(q * len(samples))) - 1
            return round(samples[max(0, min(idx, len(samples) - 1))], 4)

        avg_val = round(sum(samples) / len(samples), 4)
        return {
            "p50": _quantile(0.50),
            "p90": _quantile(0.90),
            "p95": _quantile(0.95),
            "p99": _quantile(0.99),
            "avg": avg_val,
            "count": len(samples),
        }

    def get_all_samples(self) -> list[float]:
        with self._lock:
            all_s = []
            for s_list in self._samples.values():
                all_s.extend(s_list)
            return sorted(all_s)


class EnterpriseMetricsRegistry:
    """
    OpenTelemetry & Prometheus-compatible Enterprise Metrics Registry.
    Tracks API, RAG, Agent, LLM, and Infrastructure telemetry.
    """

    def __init__(self):
        # 1. API Metrics
        self.http_requests_total = Counter("http_requests_total", "Total incoming HTTP API requests")
        self.http_errors_total = Counter("http_errors_total", "Total HTTP 5xx and 4xx API errors")
        self.http_request_duration_seconds = Histogram("http_request_duration_seconds", "HTTP request latency in seconds")
        self.http_active_requests_gauge = Gauge("http_active_requests", "Number of currently active HTTP requests")

        # Sliding window for RPS calculation
        self._request_timestamps: list[float] = []
        self._timestamps_lock = threading.Lock()

        # 2. RAG Metrics
        self.rag_retrieval_duration_seconds = Histogram("rag_retrieval_duration_seconds", "Vector and hybrid retrieval latency")
        self.rag_reranker_duration_seconds = Histogram("rag_reranker_duration_seconds", "Cross-encoder reranking latency")
        self.rag_recall_at_k_gauge = Gauge("rag_recall_at_k", "Latest measured Recall@K evaluation score")
        self.rag_cache_hits = Counter("rag_cache_hits_total", "Total semantic RAG cache hits")
        self.rag_cache_misses = Counter("rag_cache_misses_total", "Total semantic RAG cache misses")

        # 3. Agent Metrics
        self.agent_execution_duration_seconds = Histogram("agent_execution_duration_seconds", "Total agent reasoning and workflow duration")
        self.agent_iterations = Histogram("agent_iterations", "Agent iteration count distribution")
        self.agent_tool_calls_total = Counter("agent_tool_calls_total", "Total tool calls invoked by specialists")
        self.agent_successes_total = Counter("agent_successes_total", "Total successful agent workflow runs")
        self.agent_failures_total = Counter("agent_failures_total", "Total failed or aborted agent workflow runs")

        # 4. LLM Metrics
        self.llm_requests_total = Counter("llm_requests_total", "Total foundation model invocations")
        self.llm_input_tokens_total = Counter("llm_input_tokens_total", "Total prompt input tokens consumed")
        self.llm_output_tokens_total = Counter("llm_output_tokens_total", "Total completion output tokens generated")
        self.llm_duration_seconds = Histogram("llm_duration_seconds", "LLM API response latency in seconds")
        self.llm_cost_usd_total = Counter("llm_cost_usd_total", "Cumulative token inference cost in USD")

        # 5. Infrastructure Metrics
        self.system_cpu_percent = Gauge("system_cpu_percent", "Current CPU utilization percentage")
        self.system_memory_used_bytes = Gauge("system_memory_used_bytes", "Memory used in bytes")
        self.system_memory_total_bytes = Gauge("system_memory_total_bytes", "Total system memory in bytes")
        self.system_memory_percent = Gauge("system_memory_percent", "Memory utilization percentage")
        self.queue_depth_pending_tasks = Gauge("queue_depth_pending_tasks", "Depth of pending background and ingestion tasks")
        self.db_connections_active = Gauge("db_connections_active", "Active PostgreSQL/database connections")
        self.db_connections_pool_size = Gauge("db_connections_pool_size", "Database connection pool capacity")
        self.opensearch_latency_ms = Histogram("opensearch_latency_ms", "OpenSearch cluster query/ping latency in milliseconds")

    # =========================================================================
    # Backward Compatibility Adapter for SimpleMetricsRegistry
    # =========================================================================

    @property
    def request_count(self) -> int:
        return int(self.http_requests_total.total())

    @property
    def error_count(self) -> int:
        return int(self.http_errors_total.total())

    @property
    def total_duration_seconds(self) -> float:
        samples = self.http_request_duration_seconds.get_all_samples()
        return sum(samples)

    @property
    def active_requests(self) -> int:
        return int(self.http_active_requests_gauge.get())

    @active_requests.setter
    def active_requests(self, val: int) -> None:
        self.http_active_requests_gauge.set(float(val))

    def record_request(self, duration: float, is_error: bool = False, endpoint: str = "/api", method: str = "GET") -> None:
        self.record_api_request(
            endpoint=endpoint,
            method=method,
            status_code=500 if is_error else 200,
            duration_seconds=duration,
        )

    # =========================================================================
    # Explicit Recording Telemetry Methods
    # =========================================================================

    def record_api_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_seconds: float,
        tenant_id: str | None = None,
    ) -> None:
        """Records an HTTP API request with labels, updating latency quantiles and RPS."""
        labels = {
            "endpoint": endpoint,
            "method": method,
            "status": str(status_code),
            "tenant_id": tenant_id or "system",
        }
        self.http_requests_total.inc(1.0, labels)
        self.http_request_duration_seconds.observe(duration_seconds, {"endpoint": endpoint, "status": str(status_code)})

        if status_code >= 400:
            self.http_errors_total.inc(1.0, labels)

        # Sliding window timestamp recording for RPS
        now = time.time()
        with self._timestamps_lock:
            self._request_timestamps.append(now)
            # Retain only last 60 seconds
            cutoff = now - 60.0
            while self._request_timestamps and self._request_timestamps[0] < cutoff:
                self._request_timestamps.pop(0)

    def record_rag_retrieval(
        self,
        retrieval_latency_seconds: float,
        reranker_latency_seconds: float = 0.0,
        recall_at_k: float | None = None,
        cache_hit: bool = False,
    ) -> None:
        """Records RAG pipeline metrics."""
        self.rag_retrieval_duration_seconds.observe(retrieval_latency_seconds)
        if reranker_latency_seconds > 0:
            self.rag_reranker_duration_seconds.observe(reranker_latency_seconds)
        if recall_at_k is not None:
            self.rag_recall_at_k_gauge.set(recall_at_k)
        if cache_hit:
            self.rag_cache_hits.inc(1.0)
        else:
            self.rag_cache_misses.inc(1.0)

    def record_agent_execution(
        self,
        duration_seconds: float,
        iterations: int,
        tool_calls_count: int,
        is_success: bool = True,
        tenant_id: str | None = None,
    ) -> None:
        """Records multi-agent workflow telemetry."""
        labels = {"tenant_id": tenant_id or "system"}
        self.agent_execution_duration_seconds.observe(duration_seconds, labels)
        self.agent_iterations.observe(float(iterations))
        self.agent_tool_calls_total.inc(float(tool_calls_count), labels)
        if is_success:
            self.agent_successes_total.inc(1.0, labels)
        else:
            self.agent_failures_total.inc(1.0, labels)

    def record_llm_call(
        self,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        duration_seconds: float,
        cost_usd: float = 0.0,
    ) -> None:
        """Records LLM foundation model telemetry."""
        labels = {"model": model, "provider": provider}
        self.llm_requests_total.inc(1.0, labels)
        self.llm_input_tokens_total.inc(float(input_tokens), labels)
        self.llm_output_tokens_total.inc(float(output_tokens), labels)
        self.llm_duration_seconds.observe(duration_seconds, labels)
        if cost_usd > 0:
            self.llm_cost_usd_total.inc(cost_usd, labels)

    def record_infrastructure(
        self,
        cpu_percent: float,
        memory_used_bytes: float,
        memory_total_bytes: float,
        queue_depth: int = 0,
        db_connections_active: int = 0,
        db_pool_size: int = 20,
        opensearch_latency_ms: float = 0.0,
    ) -> None:
        """Records infrastructure health metrics."""
        self.system_cpu_percent.set(cpu_percent)
        self.system_memory_used_bytes.set(memory_used_bytes)
        self.system_memory_total_bytes.set(memory_total_bytes)
        mem_pct = (memory_used_bytes / memory_total_bytes * 100.0) if memory_total_bytes > 0 else 0.0
        self.system_memory_percent.set(round(mem_pct, 2))
        self.queue_depth_pending_tasks.set(float(queue_depth))
        self.db_connections_active.set(float(db_connections_active))
        self.db_connections_pool_size.set(float(db_pool_size))
        if opensearch_latency_ms > 0:
            self.opensearch_latency_ms.observe(opensearch_latency_ms)

    # =========================================================================
    # Aggregated Summaries & Golden Signals
    # =========================================================================

    def get_rps(self) -> float:
        """Calculates current Requests Per Second over last 60 seconds."""
        now = time.time()
        with self._timestamps_lock:
            valid_stamps = [t for t in self._request_timestamps if t >= (now - 60.0)]
            if not valid_stamps:
                return 0.0
            time_span = max(1.0, now - valid_stamps[0])
            return round(len(valid_stamps) / time_span, 2)

    def get_api_metrics(self) -> dict[str, Any]:
        """Returns API golden signal metrics (RPS, p50, p95, p99, error rate)."""
        all_samples = self.http_request_duration_seconds.get_all_samples()
        total_reqs = self.http_requests_total.total()
        total_errs = self.http_errors_total.total()
        error_rate = round((total_errs / total_reqs), 4) if total_reqs > 0 else 0.0

        if all_samples:
            def _pct(q: float) -> float:
                idx = int(math.ceil(q * len(all_samples))) - 1
                return round(all_samples[max(0, min(idx, len(all_samples) - 1))] * 1000.0, 2)  # in ms
            p50 = _pct(0.50)
            p90 = _pct(0.90)
            p95 = _pct(0.95)
            p99 = _pct(0.99)
            avg = round((sum(all_samples) / len(all_samples)) * 1000.0, 2)
        else:
            p50 = p90 = p95 = p99 = avg = 0.0

        return {
            "rps": self.get_rps(),
            "p50_latency_ms": p50,
            "p90_latency_ms": p90,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "avg_latency_ms": avg,
            "error_rate": error_rate,
            "total_requests": int(total_reqs),
            "total_errors": int(total_errs),
            "active_requests": int(self.http_active_requests_gauge.get()),
        }

    def get_rag_metrics(self) -> dict[str, Any]:
        """Returns RAG evaluation and operational metrics."""
        hits = self.rag_cache_hits.total()
        misses = self.rag_cache_misses.total()
        total_lookups = hits + misses
        cache_hit_ratio = round(hits / total_lookups, 4) if total_lookups > 0 else 0.0

        retrieval_quantiles = self.rag_retrieval_duration_seconds.get_quantiles()
        reranker_quantiles = self.rag_reranker_duration_seconds.get_quantiles()

        return {
            "retrieval_latency_ms": {
                "p50": round(retrieval_quantiles["p50"] * 1000.0, 2),
                "p95": round(retrieval_quantiles["p95"] * 1000.0, 2),
                "p99": round(retrieval_quantiles["p99"] * 1000.0, 2),
                "avg": round(retrieval_quantiles["avg"] * 1000.0, 2),
            },
            "reranker_latency_ms": {
                "p50": round(reranker_quantiles["p50"] * 1000.0, 2),
                "p95": round(reranker_quantiles["p95"] * 1000.0, 2),
                "p99": round(reranker_quantiles["p99"] * 1000.0, 2),
            },
            "recall_at_k": round(self.rag_recall_at_k_gauge.get(), 4),
            "cache_hit_ratio": cache_hit_ratio,
            "cache_hits_total": int(hits),
            "cache_misses_total": int(misses),
        }

    def get_agent_metrics(self) -> dict[str, Any]:
        """Returns multi-agent reasoning metrics."""
        dur_quantiles = self.agent_execution_duration_seconds.get_quantiles()
        iter_quantiles = self.agent_iterations.get_quantiles()
        succ = self.agent_successes_total.total()
        fail = self.agent_failures_total.total()
        total_runs = succ + fail
        success_rate = round(succ / total_runs, 4) if total_runs > 0 else 1.0
        failure_rate = round(fail / total_runs, 4) if total_runs > 0 else 0.0

        return {
            "execution_time_seconds": {
                "p50": dur_quantiles["p50"],
                "p95": dur_quantiles["p95"],
                "p99": dur_quantiles["p99"],
                "avg": dur_quantiles["avg"],
            },
            "iterations": {
                "avg": iter_quantiles["avg"],
                "p95": iter_quantiles["p95"],
            },
            "total_tool_calls": int(self.agent_tool_calls_total.total()),
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "total_completed_workflows": int(total_runs),
        }

    def get_llm_metrics(self) -> dict[str, Any]:
        """Returns LLM accounting and performance metrics."""
        dur_quantiles = self.llm_duration_seconds.get_quantiles()
        return {
            "total_requests": int(self.llm_requests_total.total()),
            "input_tokens": int(self.llm_input_tokens_total.total()),
            "output_tokens": int(self.llm_output_tokens_total.total()),
            "total_tokens": int(self.llm_input_tokens_total.total() + self.llm_output_tokens_total.total()),
            "latency_ms": {
                "p50": round(dur_quantiles["p50"] * 1000.0, 2),
                "p95": round(dur_quantiles["p95"] * 1000.0, 2),
                "p99": round(dur_quantiles["p99"] * 1000.0, 2),
            },
            "total_cost_usd": round(self.llm_cost_usd_total.total(), 6),
        }

    def get_infrastructure_metrics(self) -> dict[str, Any]:
        """Returns infrastructure telemetry."""
        opensearch_q = self.opensearch_latency_ms.get_quantiles()
        return {
            "cpu_percent": self.system_cpu_percent.get(),
            "memory": {
                "used_bytes": int(self.system_memory_used_bytes.get()),
                "total_bytes": int(self.system_memory_total_bytes.get()),
                "percent": self.system_memory_percent.get(),
            },
            "queue_depth": int(self.queue_depth_pending_tasks.get()),
            "database_connections": {
                "active": int(self.db_connections_active.get()),
                "pool_size": int(self.db_connections_pool_size.get()),
            },
            "opensearch_latency_ms": {
                "p50": opensearch_q["p50"],
                "p95": opensearch_q["p95"],
                "avg": opensearch_q["avg"],
            },
        }

    def get_metrics_summary(self) -> dict[str, Any]:
        """Returns complete platform metrics dictionary across all 5 operational pillars."""
        return {
            "api": self.get_api_metrics(),
            "rag": self.get_rag_metrics(),
            "agent": self.get_agent_metrics(),
            "llm": self.get_llm_metrics(),
            "infrastructure": self.get_infrastructure_metrics(),
            # Legacy fields for backward compatibility
            "http_requests_total": int(self.http_requests_total.total()),
            "http_errors_total": int(self.http_errors_total.total()),
            "http_avg_duration_seconds": round(self.get_api_metrics()["avg_latency_ms"] / 1000.0, 4),
            "http_active_requests": int(self.http_active_requests_gauge.get()),
        }

    def generate_prometheus_exposition(self) -> str:
        """
        Renders OpenTelemetry / Prometheus text exposition format.
        Produces compliant '# HELP', '# TYPE', and metric key-value lines with labels.
        """
        lines: list[str] = [
            "# HELP http_requests_total Total HTTP requests processed",
            "# TYPE http_requests_total counter",
        ]
        for labels, val in self.http_requests_total.get_all().items():
            label_str = ",".join(f'{k}="{v}"' for k, v in labels)
            lines.append(f"http_requests_total{{{label_str}}} {val}")

        lines.extend([
            "# HELP http_errors_total Total HTTP error requests",
            "# TYPE http_errors_total counter",
        ])
        for labels, val in self.http_errors_total.get_all().items():
            label_str = ",".join(f'{k}="{v}"' for k, v in labels)
            lines.append(f"http_errors_total{{{label_str}}} {val}")

        api_m = self.get_api_metrics()
        lines.extend([
            f"http_rps {api_m['rps']}",
            f"http_p50_latency_ms {api_m['p50_latency_ms']}",
            f"http_p95_latency_ms {api_m['p95_latency_ms']}",
            f"http_p99_latency_ms {api_m['p99_latency_ms']}",
            f"http_error_rate {api_m['error_rate']}",
        ])

        # RAG
        rag_m = self.get_rag_metrics()
        lines.extend([
            f"rag_retrieval_latency_p95_ms {rag_m['retrieval_latency_ms']['p95']}",
            f"rag_reranker_latency_p95_ms {rag_m['reranker_latency_ms']['p95']}",
            f"rag_recall_at_k {rag_m['recall_at_k']}",
            f"rag_cache_hit_ratio {rag_m['cache_hit_ratio']}",
        ])

        # Agent
        ag_m = self.get_agent_metrics()
        lines.extend([
            f"agent_execution_time_p95_seconds {ag_m['execution_time_seconds']['p95']}",
            f"agent_iterations_avg {ag_m['iterations']['avg']}",
            f"agent_tool_calls_total {ag_m['total_tool_calls']}",
            f"agent_success_rate {ag_m['success_rate']}",
            f"agent_failure_rate {ag_m['failure_rate']}",
        ])

        # LLM
        llm_m = self.get_llm_metrics()
        lines.extend([
            f"llm_requests_total {llm_m['total_requests']}",
            f"llm_input_tokens_total {llm_m['input_tokens']}",
            f"llm_output_tokens_total {llm_m['output_tokens']}",
            f"llm_cost_usd_total {llm_m['total_cost_usd']}",
        ])

        # Infrastructure
        infra_m = self.get_infrastructure_metrics()
        lines.extend([
            f"system_cpu_percent {infra_m['cpu_percent']}",
            f"system_memory_percent {infra_m['memory']['percent']}",
            f"queue_depth_pending_tasks {infra_m['queue_depth']}",
            f"db_connections_active {infra_m['database_connections']['active']}",
            f"opensearch_latency_p95_ms {infra_m['opensearch_latency_ms']['p95']}",
        ])

        return "\n".join(lines) + "\n"


# Singleton Metrics Registry
metrics_registry = EnterpriseMetricsRegistry()
SimpleMetricsRegistry = EnterpriseMetricsRegistry  # Alias for backward compatibility
