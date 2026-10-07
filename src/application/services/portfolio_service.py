from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Holding, Portfolio, RiskAssessment
from ...infrastructure.repositories.pagination import PagedResult, PageParams
from ...infrastructure.repositories.portfolio_repository import PortfolioRepository
from ...security.context import RequestSecurityContext
from ...security.rbac import enforce_permission, enforce_tenant_isolation


class PortfolioService:
    """Service layer for institutional portfolios, holdings, and quantitative risk assessments."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PortfolioRepository(session)

    async def get_portfolio(self, context: RequestSecurityContext, portfolio_id: str) -> Portfolio:
        """Retrieves portfolio enforcing portfolios:read and tenant boundary."""
        enforce_permission(context, "portfolios:read")
        portfolio = await self.repo.get_by_id(tenant_id=context.tenant_id, portfolio_id=portfolio_id)
        enforce_tenant_isolation(context, portfolio.tenant_id)
        return portfolio

    async def list_portfolios(self, context: RequestSecurityContext, limit: int = 50, offset: int = 0) -> list[Portfolio]:
        """Lists portfolios strictly for context.tenant_id."""
        enforce_permission(context, "portfolios:read")
        return await self.repo.list_by_tenant(tenant_id=context.tenant_id, limit=limit, offset=offset)

    async def list_paginated(
        self,
        context: RequestSecurityContext,
        page_params: PageParams,
    ) -> PagedResult[Portfolio]:
        """Returns paginated portfolios."""
        enforce_permission(context, "portfolios:read")
        return await self.repo.list_paginated(tenant_id=context.tenant_id, page_params=page_params)

    async def create_portfolio(
        self,
        context: RequestSecurityContext,
        name: str,
        benchmark: str = "SPY",
        total_value: float = 0.0,
        positions_json: str = "[]",
        description: str = "",
        currency: str = "USD",
    ) -> Portfolio:
        """Creates portfolio verifying portfolios:write permission."""
        enforce_permission(context, "portfolios:write")
        return await self.repo.create(
            tenant_id=context.tenant_id,
            name=name,
            benchmark=benchmark,
            total_value=total_value,
            positions_json=positions_json,
            description=description,
            currency=currency,
        )

    async def add_holding(
        self,
        context: RequestSecurityContext,
        portfolio_id: str,
        ticker: str,
        shares: float,
        market_price: float,
        market_value: float,
        weight: float,
        cost_basis: float = 0.0,
        asset_class: str = "EQUITY",
    ) -> Holding:
        """Attaches a holding position to a portfolio."""
        enforce_permission(context, "portfolios:write")
        return await self.repo.add_holding(
            tenant_id=context.tenant_id,
            portfolio_id=portfolio_id,
            ticker=ticker,
            shares=shares,
            market_price=market_price,
            market_value=market_value,
            weight=weight,
            cost_basis=cost_basis,
            asset_class=asset_class,
        )

    async def add_risk_assessment(
        self,
        context: RequestSecurityContext,
        portfolio_id: str,
        metric_value: float,
        assessment_type: str = "VAR",
        confidence_level: float = 0.99,
        horizon_days: int = 20,
        rating: str = "LOW",
        details_json: str = "{}",
        requires_hitl: bool = False,
    ) -> RiskAssessment:
        """Records a risk computation on the portfolio."""
        enforce_permission(context, "risk:execute")
        return await self.repo.add_risk_assessment(
            tenant_id=context.tenant_id,
            portfolio_id=portfolio_id,
            metric_value=metric_value,
            assessment_type=assessment_type,
            confidence_level=confidence_level,
            horizon_days=horizon_days,
            rating=rating,
            details_json=details_json,
            requires_hitl=requires_hitl,
        )

    async def rebalance_portfolio(
        self,
        context: RequestSecurityContext,
        portfolio_id: str,
        expected_version: int,
        new_total_value: float,
        description: str | None = None,
    ) -> Portfolio:
        """Updates portfolio valuation with optimistic concurrency conflict detection."""
        enforce_permission(context, "portfolios:write")
        return await self.repo.update_with_optimistic_lock(
            tenant_id=context.tenant_id,
            portfolio_id=portfolio_id,
            expected_version=expected_version,
            total_value=new_total_value,
            description=description,
        )

    async def delete_portfolio(self, context: RequestSecurityContext, portfolio_id: str) -> None:
        """Soft-deletes a portfolio."""
        enforce_permission(context, "portfolios:delete")
        await self.repo.soft_delete(tenant_id=context.tenant_id, portfolio_id=portfolio_id)
