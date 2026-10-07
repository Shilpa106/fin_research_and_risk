import hashlib
import time
from dataclasses import dataclass

from .models import LLMRequest, LLMResponse


@dataclass
class CacheEntry:
    response: LLMResponse
    expires_at: float


class GatewayCache:
    """
    Deterministic response cache for idempotent queries.
    Strictly namespaces cache keys by tenant_id to prevent any cross-tenant data leakage.
    """

    def __init__(self, default_ttl_seconds: float = 3600.0):
        self.default_ttl = default_ttl_seconds
        self._cache: dict[str, CacheEntry] = {}

    def _generate_key(self, request: LLMRequest, model: str) -> str:
        """Computes secure SHA-256 digest keyed strictly to tenant_id and request parameters."""
        raw_key = (
            f"tenant:{request.tenant_id}:"
            f"model:{model}:"
            f"sys:{request.system_prompt or ''}:"
            f"prompt:{request.prompt.strip()}:"
            f"temp:{request.temperature}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def get(self, request: LLMRequest, model: str) -> LLMResponse | None:
        """Retrieves cached response if valid and not expired."""
        if not request.cacheable:
            return None

        key = self._generate_key(request, model)
        entry = self._cache.get(key)
        if not entry:
            return None

        now = time.time()
        if now > entry.expires_at:
            del self._cache[key]
            return None

        # Return clone with updated request_id and cached=True
        cached_resp = LLMResponse(
            content=entry.response.content,
            input_tokens=entry.response.input_tokens,
            output_tokens=entry.response.output_tokens,
            total_tokens=entry.response.total_tokens,
            latency_ms=0.5,
            estimated_cost_usd=0.0,  # Zero extra cost for cache hits
            model=entry.response.model,
            provider=entry.response.provider,
            request_id=request.request_id,
            tenant_id=request.tenant_id,
            prompt_version=request.prompt_version,
            cached=True,
            fallback_used=False,
            finish_reason=entry.response.finish_reason,
            metadata={"cache_hit": True, "cached_at": entry.expires_at - self.default_ttl},
        )
        return cached_resp

    def set(
        self,
        request: LLMRequest,
        model: str,
        response: LLMResponse,
        ttl_seconds: float | None = None,
    ) -> None:
        """Stores response in cache if request is cacheable."""
        if not request.cacheable:
            return

        key = self._generate_key(request, model)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        self._cache[key] = CacheEntry(
            response=response,
            expires_at=time.time() + ttl,
        )

    def clear(self) -> None:
        """Clears all cached entries."""
        self._cache.clear()
