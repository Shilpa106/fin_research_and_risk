import collections
import time

from ..domain.exceptions import RateLimitExceededException


class GatewayRateLimiter:
    """
    Sliding-window rate limiter per tenant and user.
    Prevents noisy tenants from starving cluster concurrency.
    """

    def __init__(self, default_rpm: int = 120):
        self.default_rpm = default_rpm
        self.tenant_rpm_limits: dict[str, int] = {}
        # Stores timestamps of recent requests per key
        self._history: collections.defaultdict[str, collections.deque[float]] = collections.defaultdict(collections.deque)

    def set_tenant_limit(self, tenant_id: str, requests_per_minute: int) -> None:
        """Sets custom RPM ceiling for a tenant."""
        self.tenant_rpm_limits[tenant_id] = requests_per_minute

    def check_and_acquire(self, tenant_id: str, user_id: str | None = None) -> None:
        """
        Validates rate limit for tenant. Raises RateLimitExceededException if exceeded.
        """
        now = time.time()
        window_start = now - 60.0
        limit = self.tenant_rpm_limits.get(tenant_id, self.default_rpm)

        key = f"tenant:{tenant_id}"
        q = self._history[key]

        # Evict timestamps older than 60 seconds
        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= limit:
            retry_after = max(1, int(60.0 - (now - q[0])))
            raise RateLimitExceededException(
                retry_after=retry_after,
                message=f"AI Gateway rate limit exceeded for tenant '{tenant_id}' ({len(q)}/{limit} RPM).",
            )

        q.append(now)
