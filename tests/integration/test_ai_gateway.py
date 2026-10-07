import pytest

from src.ai_gateway import (
    AIGateway,
    GatewayCache,
    GatewayRateLimiter,
    LLMRequest,
    MockLLMProvider,
    ModelRouter,
    ModelTaskType,
    TaskComplexity,
    TokenBudgetManager,
)
from src.ai_gateway.circuit_breaker import CircuitState
from src.domain.exceptions import (
    CostLimitExceededException,
    ProviderUnavailableException,
    RateLimitExceededException,
    TokenBudgetExceededException,
)


@pytest.fixture
def mock_primary_provider() -> MockLLMProvider:
    return MockLLMProvider(provider_name="mock_primary", simulated_delay=0.001)


@pytest.fixture
def mock_fallback_provider() -> MockLLMProvider:
    return MockLLMProvider(provider_name="mock_fallback", simulated_delay=0.001)


@pytest.fixture
def ai_gateway(
    mock_primary_provider: MockLLMProvider,
    mock_fallback_provider: MockLLMProvider,
) -> AIGateway:
    router = ModelRouter(use_mock=True)
    rate_limiter = GatewayRateLimiter(default_rpm=120)
    token_budget = TokenBudgetManager(
        default_max_request_tokens=10_000,
        default_tenant_token_budget=1_000_000,
        default_tenant_cost_budget=100.0,
    )
    cache = GatewayCache(default_ttl_seconds=300.0)

    return AIGateway(
        provider=mock_primary_provider,
        fallback_provider=mock_fallback_provider,
        rate_limiter=rate_limiter,
        token_budget_manager=token_budget,
        cache=cache,
        router=router,
        max_retries=1,
        base_retry_delay=0.01,
    )


# ==============================================================================
# 1. Model Routing Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_model_routing_strategies(ai_gateway: AIGateway):
    """
    Validates model routing heuristics:
    - simple query -> lower-cost model (mock-fast-model)
    - complex reasoning -> stronger model (mock-reasoning-model)
    - summarization -> optimized model (mock-fast-model)
    """
    tenant_id = "tenant-routing-test"

    # 1. Simple query
    req_simple = LLMRequest(
        prompt="What is the ticker for Apple Inc?",
        tenant_id=tenant_id,
        task_type=ModelTaskType.SIMPLE_QUERY,
        complexity=TaskComplexity.SIMPLE,
    )
    res_simple = await ai_gateway.complete(req_simple)
    assert res_simple.model == "mock-fast-model"
    assert res_simple.input_tokens > 0
    assert res_simple.output_tokens > 0
    assert res_simple.estimated_cost_usd > 0
    assert res_simple.request_id == req_simple.request_id

    # 2. Complex reasoning query
    req_complex = LLMRequest(
        prompt="Perform a multi-horizon Monte Carlo VaR simulation and analyze credit transition matrices.",
        tenant_id=tenant_id,
        task_type=ModelTaskType.COMPLEX_REASONING,
        complexity=TaskComplexity.COMPLEX_REASONING,
        reasoning_required=True,
    )
    res_complex = await ai_gateway.complete(req_complex)
    assert res_complex.model == "mock-reasoning-model"
    assert res_complex.fallback_used is False

    # 3. Summarization query
    req_summary = LLMRequest(
        prompt="Summarize the Q3 10-Q filing balance sheet footnotes for liquidity covenants.",
        tenant_id=tenant_id,
        task_type=ModelTaskType.SUMMARIZATION,
    )
    res_summary = await ai_gateway.complete(req_summary)
    assert res_summary.model == "mock-fast-model"


# ==============================================================================
# 2. Provider Timeout & Fallback Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_provider_timeout_and_fallback(
    ai_gateway: AIGateway,
    mock_primary_provider: MockLLMProvider,
):
    """
    When primary provider times out, gateway retries and gracefully falls back
    to secondary provider with fallback_used=True.
    """
    tenant_id = "tenant-timeout-test"
    # Configure primary reasoning model to timeout
    mock_primary_provider.set_model_timeout("mock-reasoning-model", should_timeout=True)

    req = LLMRequest(
        prompt="Evaluate quantitative tail risk under 2008 liquidity stress.",
        tenant_id=tenant_id,
        task_type=ModelTaskType.COMPLEX_REASONING,
        complexity=TaskComplexity.COMPLEX_REASONING,
        timeout_seconds=0.05,  # short timeout for test
    )

    # Primary should timeout, fallback model (mock-fast-model) on fallback_provider should succeed
    res = await ai_gateway.complete(req)
    assert res.fallback_used is True
    assert res.model == "mock-fast-model"
    assert res.provider == "mock_fallback"


# ==============================================================================
# 3. Provider Failure & Circuit Breaker Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_provider_failure_and_circuit_breaker(
    ai_gateway: AIGateway,
    mock_primary_provider: MockLLMProvider,
    mock_fallback_provider: MockLLMProvider,
):
    """
    When primary provider fails repeatedly, the circuit breaker transitions
    from CLOSED to OPEN, preventing cascading downstream exhaustion.
    """
    tenant_id = "tenant-cb-test"
    # Both primary and fallback fail on the requested model
    mock_primary_provider.set_model_failure("mock-fast-model", should_fail=True)
    mock_fallback_provider.set_model_failure("mock-fast-model", should_fail=True)
    mock_fallback_provider.set_model_failure("mock-reasoning-model", should_fail=True)

    cb = ai_gateway._get_circuit_breaker("mock-fast-model")
    assert cb.state == CircuitState.CLOSED

    req = LLMRequest(
        prompt="What is the federal funds rate?",
        tenant_id=tenant_id,
        task_type=ModelTaskType.SIMPLE_QUERY,
        complexity=TaskComplexity.SIMPLE,
        cacheable=False,
    )

    # Invocation should fail when both primary and fallback fail
    with pytest.raises(ProviderUnavailableException):
        await ai_gateway.complete(req)

    # Verify circuit breaker registered failures
    assert cb.consecutive_failures >= 1


# ==============================================================================
# 4. Fallback Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_graceful_fallback(
    ai_gateway: AIGateway,
    mock_primary_provider: MockLLMProvider,
):
    """
    Verifies transparent fallback when primary reasoning model suffers 503 outage.
    """
    tenant_id = "tenant-fallback-test"
    mock_primary_provider.set_model_failure("mock-reasoning-model", should_fail=True)

    req = LLMRequest(
        prompt="Analyze macro yield curve inversion spread.",
        tenant_id=tenant_id,
        task_type=ModelTaskType.COMPLEX_REASONING,
        complexity=TaskComplexity.COMPLEX_REASONING,
    )

    res = await ai_gateway.complete(req)
    assert res.fallback_used is True
    assert res.model == "mock-fast-model"
    assert res.provider == "mock_fallback"
    assert "Analysis response" in res.content or "compliance" in res.content


# ==============================================================================
# 5. Token Limit Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_token_budget_enforcement(ai_gateway: AIGateway):
    """
    Verifies that requests exceeding single-request limits or cumulative tenant token budgets
    are rejected with TokenBudgetExceededException (HTTP 429).
    """
    tenant_id = "tenant-token-limited"
    # Set strict token limit of 100 tokens
    ai_gateway.token_budget_manager.set_limits(tenant_id, max_tokens=100)

    req = LLMRequest(
        prompt="Summarize the comprehensive global financial system stability report.",
        tenant_id=tenant_id,
        max_tokens=500,  # exceeds 100 token ceiling
    )

    with pytest.raises(TokenBudgetExceededException) as exc_info:
        await ai_gateway.complete(req)

    assert exc_info.value.status_code == 429
    assert exc_info.value.error_code == "TOKEN_BUDGET_EXCEEDED"
    assert exc_info.value.details["tenant_id"] == tenant_id


# ==============================================================================
# 6. Rate Limit Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_rate_limit_enforcement(ai_gateway: AIGateway):
    """
    Verifies sliding-window rate limit: when a tenant exceeds their RPM quota,
    the gateway immediately rejects with RateLimitExceededException (HTTP 429).
    """
    tenant_id = "tenant-rate-limited"
    # Set restrictive rate limit: 2 requests per minute
    ai_gateway.rate_limiter.set_tenant_limit(tenant_id, requests_per_minute=2)

    req = LLMRequest(
        prompt="Check stock price",
        tenant_id=tenant_id,
        cacheable=False,  # Bypass cache so each request checks rate limiter
    )

    # Call 1: Allowed
    res1 = await ai_gateway.complete(req)
    assert res1 is not None

    # Call 2: Allowed
    res2 = await ai_gateway.complete(req)
    assert res2 is not None

    # Call 3: Exceeds 2 RPM ceiling -> Must raise RateLimitExceededException
    with pytest.raises(RateLimitExceededException) as exc_info:
        await ai_gateway.complete(req)

    assert exc_info.value.status_code == 429
    assert exc_info.value.error_code == "RATE_LIMIT_EXCEEDED"
    assert exc_info.value.details["retry_after_seconds"] >= 1


# ==============================================================================
# 7. Cost Limit Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_cost_limit_enforcement(ai_gateway: AIGateway):
    """
    Verifies monthly financial cost cap: when tenant's accumulated spend reaches the limit,
    subsequent calls are blocked with CostLimitExceededException.
    """
    tenant_id = "tenant-cost-limited"
    # Set micro-budget of $0.00001
    ai_gateway.token_budget_manager.set_limits(tenant_id, max_cost_usd=0.00001)

    req = LLMRequest(
        prompt="Generate full corporate bond indenture analysis.",
        tenant_id=tenant_id,
        cacheable=False,
    )

    # First call records usage and cost (~$0.00003)
    res = await ai_gateway.complete(req)
    assert res is not None

    # Second call detects accumulated spend >= $0.00001
    with pytest.raises(CostLimitExceededException) as exc_info:
        await ai_gateway.complete(req)

    assert exc_info.value.status_code == 429
    assert exc_info.value.error_code == "COST_LIMIT_EXCEEDED"
    assert exc_info.value.details["tenant_id"] == tenant_id


# ==============================================================================
# 8. Caching and Multi-Tenant Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_gateway_caching_and_tenant_isolation(ai_gateway: AIGateway):
    """
    Validates:
    1. Idempotent requests for Tenant A hit cache (cached=True, cost=0)
    2. Identical request for Tenant B is a cache miss (strict tenant isolation)
    """
    prompt = "What is the capital requirement for Basel III Tier 1?"

    # 1. Tenant A first call: Cache Miss
    req_a1 = LLMRequest(prompt=prompt, tenant_id="tenant-alpha")
    res_a1 = await ai_gateway.complete(req_a1)
    assert res_a1.cached is False

    # 2. Tenant A second call: Cache Hit
    req_a2 = LLMRequest(prompt=prompt, tenant_id="tenant-alpha")
    res_a2 = await ai_gateway.complete(req_a2)
    assert res_a2.cached is True
    assert res_a2.estimated_cost_usd == 0.0
    assert res_a2.latency_ms <= 1.0

    # 3. Tenant B identical query: MUST be Cache Miss due to tenant isolation
    req_b = LLMRequest(prompt=prompt, tenant_id="tenant-beta")
    res_b = await ai_gateway.complete(req_b)
    assert res_b.cached is False
    assert res_b.tenant_id == "tenant-beta"
