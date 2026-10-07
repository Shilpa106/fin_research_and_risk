from dataclasses import dataclass

from ..domain.exceptions import CostLimitExceededException, TokenBudgetExceededException


@dataclass
class TenantUsageStats:
    """Aggregated usage statistics for a tenant."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    total_cost_usd: float = 0.0


class TokenBudgetManager:
    """
    Tracks and enforces token quotas and expenditure budgets across tenants.
    Guarantees strict financial boundaries to eliminate runaway LLM bills.
    """

    def __init__(
        self,
        default_max_request_tokens: int = 128_000,
        default_tenant_token_budget: int = 50_000_000,
        default_tenant_cost_budget: float = 5_000.0,
    ):
        self.default_max_request_tokens = default_max_request_tokens
        self.default_tenant_token_budget = default_tenant_token_budget
        self.default_tenant_cost_budget = default_tenant_cost_budget

        self._usage: dict[str, TenantUsageStats] = {}
        self._token_limits: dict[str, int] = {}
        self._cost_limits: dict[str, float] = {}

    def set_limits(
        self,
        tenant_id: str,
        max_tokens: int | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        """Sets customized token or cost ceilings for an enterprise tenant."""
        if max_tokens is not None:
            self._token_limits[tenant_id] = max_tokens
        if max_cost_usd is not None:
            self._cost_limits[tenant_id] = max_cost_usd

    def check_budget(
        self,
        tenant_id: str,
        estimated_input_tokens: int,
        requested_max_output_tokens: int,
    ) -> None:
        """
        Pre-flight verification of token quotas and financial limits.
        Raises TokenBudgetExceededException or CostLimitExceededException if exceeded.
        """
        # 1. Check single-request boundary
        total_requested = estimated_input_tokens + requested_max_output_tokens
        if total_requested > self.default_max_request_tokens:
            raise TokenBudgetExceededException(
                tenant_id=tenant_id,
                requested_tokens=total_requested,
                remaining_budget=self.default_max_request_tokens,
            )

        usage = self._usage.get(tenant_id, TenantUsageStats())
        token_limit = self._token_limits.get(tenant_id, self.default_tenant_token_budget)
        cost_limit = self._cost_limits.get(tenant_id, self.default_tenant_cost_budget)

        # 2. Check cumulative token budget
        projected_tokens = usage.total_input_tokens + usage.total_output_tokens + total_requested
        if projected_tokens > token_limit:
            remaining = max(0, token_limit - (usage.total_input_tokens + usage.total_output_tokens))
            raise TokenBudgetExceededException(
                tenant_id=tenant_id,
                requested_tokens=total_requested,
                remaining_budget=remaining,
            )

        # 3. Check cumulative cost budget
        if usage.total_cost_usd >= cost_limit:
            raise CostLimitExceededException(
                tenant_id=tenant_id,
                accumulated_cost=usage.total_cost_usd,
                cost_limit=cost_limit,
            )

    def record_usage(
        self,
        tenant_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Records finalized token consumption and charges to tenant's usage balance."""
        if tenant_id not in self._usage:
            self._usage[tenant_id] = TenantUsageStats()

        stat = self._usage[tenant_id]
        stat.total_input_tokens += input_tokens
        stat.total_output_tokens += output_tokens
        stat.total_requests += 1
        stat.total_cost_usd = round(stat.total_cost_usd + cost_usd, 6)

    def get_usage(self, tenant_id: str) -> TenantUsageStats:
        """Retrieves tenant usage telemetry."""
        return self._usage.get(tenant_id, TenantUsageStats())
