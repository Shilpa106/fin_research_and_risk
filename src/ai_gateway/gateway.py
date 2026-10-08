import asyncio
import hashlib
import logging
import time
from typing import Any

from ..observability.integrations import langsmith_exporter
from ..observability.metrics import metrics_registry
from ..observability.tracing import SpanKind, default_tracer

from ..domain.exceptions import (
    CircuitBreakerOpenException,
    ProviderTimeoutException,
    ProviderUnavailableException,
)
from ..interfaces.ai_gateway import AIGatewayInterface
from .cache import GatewayCache
from .circuit_breaker import CircuitBreaker
from .models import (
    LLMRequest,
    LLMResponse,
    ModelTaskType,
    TaskComplexity,
)
from .providers.base import LLMProvider
from .providers.mock_provider import MockLLMProvider
from .rate_limiter import GatewayRateLimiter
from .router import ModelRouter
from .token_budget import TokenBudgetManager

logger = logging.getLogger("enterprise_copilot.ai_gateway")


class AIGateway(AIGatewayInterface):
    """
    Enterprise AI Gateway.
    Centralized, resilient control plane governing all foundation model interactions.

    Core Responsibilities:
    - Model routing based on complexity, reasoning, latency, and cost
    - Provider abstraction (AWS Bedrock, Local Mock)
    - Rate limiting per tenant
    - Token budgeting & financial cost enforcement
    - Circuit breaking per model/provider
    - Automated retries with exponential backoff
    - Graceful fallback on primary provider failure
    - Tenant-isolated deterministic response caching
    - Zero-leakage observability (never logs sensitive prompts or secrets)
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        fallback_provider: LLMProvider | None = None,
        rate_limiter: GatewayRateLimiter | None = None,
        token_budget_manager: TokenBudgetManager | None = None,
        cache: GatewayCache | None = None,
        router: ModelRouter | None = None,
        max_retries: int = 2,
        base_retry_delay: float = 0.05,
    ):
        # Default providers: if no provider specified, use MockLLMProvider for offline safety
        self.provider = provider or MockLLMProvider()
        self.fallback_provider = fallback_provider or MockLLMProvider(provider_name="mock_fallback")

        self.rate_limiter = rate_limiter or GatewayRateLimiter()
        self.token_budget_manager = token_budget_manager or TokenBudgetManager()
        self.cache = cache or GatewayCache()
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay

        # Circuit breakers registry per model
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

        # Model router
        use_mock = isinstance(self.provider, MockLLMProvider)
        self.router = router or ModelRouter(use_mock=use_mock, circuit_breakers=self.circuit_breakers)

    def _get_circuit_breaker(self, model: str) -> CircuitBreaker:
        """Retrieves or creates a dedicated circuit breaker for the model."""
        if model not in self.circuit_breakers:
            self.circuit_breakers[model] = CircuitBreaker(name=model, failure_threshold=3, recovery_timeout=15.0)
        return self.circuit_breakers[model]

    def _log_observability_telemetry(self, response: LLMResponse, prompt_digest: str) -> None:
        """
        Emits structured audit log for monitoring and cost accounting.
        SECURITY: Never logs raw prompt content, PII, financial secrets, or API keys.
        """
        logger.info(
            "AI Gateway Invocations | RequestID: %s | Tenant: %s | Model: %s | Provider: %s | "
            "InputTokens: %d | OutputTokens: %d | Latency: %.2fms | CostUSD: $%.6f | "
            "Cached: %s | Fallback: %s | PromptDigest: %s",
            response.request_id,
            response.tenant_id,
            response.model,
            response.provider,
            response.input_tokens,
            response.output_tokens,
            response.latency_ms,
            response.estimated_cost_usd,
            response.cached,
            response.fallback_used,
            prompt_digest,
        )

        # Record OpenTelemetry LLM Golden Signals & Accounting
        metrics_registry.record_llm_call(
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            duration_seconds=response.latency_ms / 1000.0,
            cost_usd=response.estimated_cost_usd,
        )

        # Record Semantic Cache Metrics
        if response.cached:
            metrics_registry.rag_cache_hits.inc(1.0)
        else:
            metrics_registry.rag_cache_misses.inc(1.0)

        # Record LangSmith-compatible run
        langsmith_exporter.capture_run(
            name=f"llm.{response.provider}.{response.model}",
            run_type="llm",
            inputs={"prompt_digest": prompt_digest, "request_id": response.request_id},
            outputs={"output_tokens": response.output_tokens, "cached": response.cached},
            start_time=time.time() - (response.latency_ms / 1000.0),
            end_time=time.time(),
            model=response.model,
            total_tokens=response.input_tokens + response.output_tokens,
            cost_usd=response.estimated_cost_usd,
            trace_id=response.request_id,
            tenant_id=response.tenant_id,
        )

    async def _execute_with_retry(
        self,
        provider: LLMProvider,
        request: LLMRequest,
        model: str,
    ) -> LLMResponse:
        """Executes LLM call with timeout and exponential backoff retry loop."""
        cb = self._get_circuit_breaker(model)
        if not cb.is_allowed():
            raise CircuitBreakerOpenException(provider=provider.provider_name, model=model)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                # Enforce request timeout
                resp = await asyncio.wait_for(
                    provider.generate(request, model),
                    timeout=request.timeout_seconds,
                )
                cb.record_success()
                return resp
            except TimeoutError:
                last_error = ProviderTimeoutException(provider.provider_name, model, request.timeout_seconds)
                cb.record_failure()
                logger.warning(
                    "Call to %s (%s) timed out on attempt %d/%d (timeout=%.1fs)",
                    provider.provider_name,
                    model,
                    attempt + 1,
                    self.max_retries + 1,
                    request.timeout_seconds,
                )
            except (ProviderUnavailableException, ProviderTimeoutException) as pe:
                last_error = pe
                cb.record_failure()
                logger.warning(
                    "Call to %s (%s) failed on attempt %d/%d: %s",
                    provider.provider_name,
                    model,
                    attempt + 1,
                    self.max_retries + 1,
                    pe,
                )
            except Exception as ex:
                last_error = ProviderUnavailableException(provider.provider_name, model, str(ex))
                cb.record_failure()
                logger.warning("Unexpected error calling %s (%s): %s", provider.provider_name, model, ex)

            if attempt < self.max_retries:
                backoff = self.base_retry_delay * (2 ** attempt)
                await asyncio.sleep(backoff)

        assert last_error is not None
        raise last_error

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Executes end-to-end governed LLM completion request.
        Flow:
        1. Rate Limiting Check
        2. Token Budget & Cost Limit Check
        3. Model Selection & Circuit Breaker Health Check
        4. Cache Lookup (if cacheable)
        5. Primary Model Execution (with retries & timeout)
        6. Automatic Fallback Execution (if primary fails)
        7. Cost & Token Accounting
        8. Response Caching
        9. Safe Observability Logging
        """
        prompt_digest = hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()[:16]

        # 1. Rate Limiting
        self.rate_limiter.check_and_acquire(request.tenant_id, request.user_id)

        # 2. Token Budget & Financial Cost Check
        estimated_input_tokens = len(request.prompt) // 4 + (len(request.system_prompt or "") // 4)
        self.token_budget_manager.check_budget(
            tenant_id=request.tenant_id,
            estimated_input_tokens=estimated_input_tokens,
            requested_max_output_tokens=request.max_tokens,
        )

        # 3. Model Routing
        primary_model, fallback_model = self.router.select_model(request)

        # 4. Safe Cache Lookup
        cached_response = self.cache.get(request, primary_model)
        if cached_response is not None:
            self._log_observability_telemetry(cached_response, prompt_digest)
            return cached_response

        response: LLMResponse | None = None
        fallback_used = False

        # 5. Primary Model Invocation
        try:
            response = await self._execute_with_retry(self.provider, request, primary_model)
        except (ProviderUnavailableException, ProviderTimeoutException, CircuitBreakerOpenException) as primary_err:
            logger.warning(
                "Primary invocation failed (%s). Triggering fallback route if available: %s",
                primary_err,
                fallback_model,
            )
            # 6. Fallback Route
            if fallback_model:
                try:
                    fallback_provider = self.fallback_provider or self.provider
                    response = await self._execute_with_retry(fallback_provider, request, fallback_model)
                    response.fallback_used = True
                    fallback_used = True
                except Exception as fb_err:
                    logger.error("Fallback route to '%s' also failed: %s", fallback_model, fb_err)
                    raise fb_err from primary_err
            else:
                raise primary_err

        assert response is not None

        # 7. Record Token & Cost Consumption
        self.token_budget_manager.record_usage(
            tenant_id=request.tenant_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.estimated_cost_usd,
        )

        # 8. Cache response if eligible
        if request.cacheable and not fallback_used:
            self.cache.set(request, primary_model, response)

        # 9. Observability & Safe Logging
        self._log_observability_telemetry(response, prompt_digest)

        return response

    # =========================================================================
    # AIGatewayInterface Compatibility Methods
    # =========================================================================

    def generate_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        use_fast_model: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Synchronous wrapper for interface compatibility."""
        req = LLMRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            tenant_id="default-tenant",
            task_type=ModelTaskType.SIMPLE_QUERY if use_fast_model else ModelTaskType.COMPLEX_REASONING,
            complexity=TaskComplexity.SIMPLE if use_fast_model else TaskComplexity.COMPLEX_REASONING,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # Execute in existing or new event loop
        try:
            asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                res = pool.submit(lambda: asyncio.run(self.complete(req))).result()
                return res.content
        except RuntimeError:
            res = asyncio.run(self.complete(req))
            return res.content

    def generate_embedding(self, text: str, dimensions: int = 1536) -> list[float]:
        """Generates deterministic mock embedding for interface compatibility."""
        import math
        vec = [0.0] * dimensions
        words = text.split()
        for idx, word in enumerate(words):
            slot = (hash(word) + idx) % dimensions
            vec[slot] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def evaluate_guardrails(self, text: str) -> dict[str, Any]:
        """Compliance guardrails evaluation for interface compatibility."""
        lower = text.lower()
        violations = []
        if "ignore previous instructions" in lower or "system prompt" in lower:
            violations.append("PROMPT_INJECTION_DETECTED")
        if any(w in lower for w in ["insider", "confidential leak", "front run"]):
            violations.append("FINANCIAL_COMPLIANCE_RESTRICTION")

        return {
            "passed": len(violations) == 0,
            "violations": violations,
            "sanitized_text": text,
        }
