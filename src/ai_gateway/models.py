import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class TaskComplexity(str, enum.Enum):
    """Complexity tier driving model routing."""
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX_REASONING = "COMPLEX_REASONING"


class LatencyRequirement(str, enum.Enum):
    """Latency SLA constraint driving model routing."""
    LOW_LATENCY = "LOW_LATENCY"
    STANDARD = "STANDARD"
    BATCH = "BATCH"


class ModelTaskType(str, enum.Enum):
    """Categorization of LLM operation."""
    SIMPLE_QUERY = "SIMPLE_QUERY"
    COMPLEX_REASONING = "COMPLEX_REASONING"
    SUMMARIZATION = "SUMMARIZATION"
    EXTRACTION = "EXTRACTION"


@dataclass(frozen=True)
class ModelPricing:
    """Pricing structure per million tokens (USD)."""
    input_cost_per_million: float
    output_cost_per_million: float


# Institutional Foundation Model Pricing Table
PRICING_REGISTRY: dict[str, ModelPricing] = {
    # Anthropic on AWS Bedrock
    "anthropic.claude-3-haiku-20240307-v1:0": ModelPricing(
        input_cost_per_million=0.25,
        output_cost_per_million=1.25,
    ),
    "anthropic.claude-3-5-sonnet-20241022-v2:0": ModelPricing(
        input_cost_per_million=3.00,
        output_cost_per_million=15.00,
    ),
    "amazon.titan-text-premier-v1:0": ModelPricing(
        input_cost_per_million=0.50,
        output_cost_per_million=1.50,
    ),
    # Local & Test Mock Models
    "mock-fast-model": ModelPricing(
        input_cost_per_million=0.25,
        output_cost_per_million=1.25,
    ),
    "mock-reasoning-model": ModelPricing(
        input_cost_per_million=3.00,
        output_cost_per_million=15.00,
    ),
}

DEFAULT_PRICING = ModelPricing(input_cost_per_million=1.00, output_cost_per_million=3.00)


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculates exact estimated USD cost for model invocation."""
    pricing = PRICING_REGISTRY.get(model_name, DEFAULT_PRICING)
    input_cost = (input_tokens / 1_000_000.0) * pricing.input_cost_per_million
    output_cost = (output_tokens / 1_000_000.0) * pricing.output_cost_per_million
    return round(input_cost + output_cost, 6)


@dataclass
class LLMRequest:
    """Standardized LLM request envelope passed into the AI Gateway."""
    prompt: str
    tenant_id: str
    system_prompt: str | None = None
    user_id: str | None = None
    task_type: ModelTaskType = ModelTaskType.SIMPLE_QUERY
    complexity: TaskComplexity = TaskComplexity.SIMPLE
    latency_req: LatencyRequirement = LatencyRequirement.STANDARD
    reasoning_required: bool = False
    context_token_estimate: int = 0
    max_tokens: int = 4096
    temperature: float = 0.1
    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:12]}")
    prompt_version: str = "v1.0"
    cacheable: bool = True
    model_override: str | None = None
    timeout_seconds: float = 30.0
    tags: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class LLMResponse:
    """Standardized LLM response envelope emitted by the AI Gateway."""
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    model: str
    provider: str
    request_id: str
    tenant_id: str
    prompt_version: str
    cached: bool = False
    fallback_used: bool = False
    finish_reason: str = "stop"
    metadata: dict[str, Any] = field(default_factory=dict)
