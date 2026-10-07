import logging

from .circuit_breaker import CircuitBreaker
from .models import (
    LatencyRequirement,
    LLMRequest,
    ModelTaskType,
    TaskComplexity,
)

logger = logging.getLogger("enterprise_copilot.ai_gateway.router")


class ModelRouter:
    """
    Intelligent routing engine selecting optimal foundation models based on:
    - Task complexity (simple vs complex)
    - Reasoning requirements (multi-step chain-of-thought)
    - Latency constraints (realtime interactive vs batch)
    - Cost efficiency
    - Context token window size
    - Realtime circuit breaker health & availability
    """

    # Production Bedrock Model IDs
    BEDROCK_FAST_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
    BEDROCK_REASONING_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    BEDROCK_FALLBACK_MODEL = "amazon.titan-text-premier-v1:0"

    # Local / Mock Model IDs
    MOCK_FAST_MODEL = "mock-fast-model"
    MOCK_REASONING_MODEL = "mock-reasoning-model"
    MOCK_FALLBACK_MODEL = "mock-fast-model"

    def __init__(
        self,
        use_mock: bool = False,
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
    ):
        self.use_mock = use_mock
        self.circuit_breakers = circuit_breakers or {}

        if use_mock:
            self.fast_model = self.MOCK_FAST_MODEL
            self.reasoning_model = self.MOCK_REASONING_MODEL
            self.fallback_model = self.MOCK_FALLBACK_MODEL
        else:
            self.fast_model = self.BEDROCK_FAST_MODEL
            self.reasoning_model = self.BEDROCK_REASONING_MODEL
            self.fallback_model = self.BEDROCK_FALLBACK_MODEL

    def _is_model_available(self, model: str) -> bool:
        """Verifies if model's circuit breaker allows calls."""
        cb = self.circuit_breakers.get(model)
        if cb and not cb.is_allowed():
            return False
        return True

    def select_model(self, request: LLMRequest) -> tuple[str, str | None]:
        """
        Selects (primary_model, fallback_model) for the given request.
        Guarantees:
        - simple query -> lower-cost model
        - complex reasoning -> stronger model
        - summarization -> optimized model
        """
        fallback: str | None = None

        # 1. Manual override if specified
        if request.model_override:
            primary = request.model_override
            fallback = self.fast_model if primary != self.fast_model else self.fallback_model
            return primary, fallback

        # 2. Complex Reasoning: requires frontier model (Sonnet / heavy reasoning)
        is_complex = (
            request.complexity == TaskComplexity.COMPLEX_REASONING
            or request.task_type == ModelTaskType.COMPLEX_REASONING
            or request.reasoning_required
        )
        if is_complex:
            primary = self.reasoning_model
            fallback = self.fast_model
            # If primary circuit is open, failover immediately to fallback
            if not self._is_model_available(primary):
                logger.warning(
                    "Primary reasoning model '%s' unavailable (circuit OPEN). Routing to fallback '%s'.",
                    primary,
                    fallback,
                )
                return fallback, None
            return primary, fallback

        # 3. Summarization: optimized fast model with large context support
        if request.task_type == ModelTaskType.SUMMARIZATION:
            primary = self.fast_model
            fallback = self.reasoning_model if self._is_model_available(self.reasoning_model) else None
            return primary, fallback

        # 4. Latency-critical or simple queries: lower-cost model (Haiku / fast mock)
        is_simple = (
            request.complexity == TaskComplexity.SIMPLE
            or request.task_type == ModelTaskType.SIMPLE_QUERY
            or request.latency_req == LatencyRequirement.LOW_LATENCY
        )
        if is_simple:
            primary = self.fast_model
            fallback = self.reasoning_model if self._is_model_available(self.reasoning_model) else None
            return primary, fallback

        # 5. Default: fast model with reasoning fallback
        primary = self.fast_model
        fallback = self.reasoning_model
        if not self._is_model_available(primary):
            return fallback, None
        return primary, fallback
