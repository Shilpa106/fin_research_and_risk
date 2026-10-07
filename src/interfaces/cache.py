from abc import ABC, abstractmethod
from typing import Any


class CacheManagerInterface(ABC):
    """
    Contract for high-throughput caching and rate limiting (10K API RPS).
    """

    @abstractmethod
    def check_rate_limit(
        self, identifier: str, cost: int = 1, rps_limit: int = 10000, burst_capacity: int = 15000
    ) -> bool:
        """
        Token bucket rate limit verification.
        """
        pass

    @abstractmethod
    def get_semantic_cache(
        self, tenant_id: str, query_vector: list[float], threshold: float = 0.96
    ) -> dict[str, Any] | None:
        """
        Semantic cache lookup via vector cosine similarity.
        """
        pass

    @abstractmethod
    def set_semantic_cache(
        self,
        tenant_id: str,
        query_hash: str,
        query_vector: list[float],
        response_payload: dict[str, Any],
        ttl_seconds: int = 3600,
    ) -> None:
        """
        Stores semantic cache entry with TTL.
        """
        pass
