from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.entities import Holding, Portfolio, RiskAssessment
from ...domain.exceptions import (
    EntityNotFoundException,
    OptimisticConcurrencyException,
    TenantIsolationViolationException,
)
from .pagination import PagedResult, PageParams, paginate_query


class PortfolioRepository:
    """
    Tenant-isolated repository for Portfolio, Holding, and RiskAssessment entities.
    Guarantees strict tenant boundaries, optimistic locking on concurrent rebalancing, and pagination.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(
        self,
        tenant_id: str,
        portfolio_id: str,
        include_deleted: bool = False,
        load_relations: bool = True,
    ) -> Portfolio:
        """Retrieves portfolio verifying tenant ownership."""
        stmt = select(Portfolio).where(Portfolio.id == portfolio_id)
        if not include_deleted:
            stmt = stmt.where(Portfolio.is_deleted == False)  # noqa: E712
        if load_relations:
            stmt = stmt.options(
                selectinload(Portfolio.holdings),
                selectinload(Portfolio.risk_assessments),
            )

        result = await self.session.execute(stmt)
        portfolio = result.scalar_one_or_none()

        if not portfolio:
            raise EntityNotFoundException("Portfolio", portfolio_id)

        # REPOSITORY-LAYER TENANT ISOLATION CHECK
        if portfolio.tenant_id != tenant_id:
            raise TenantIsolationViolationException(
                f"Portfolio '{portfolio_id}' belongs to tenant '{portfolio.tenant_id}', but was accessed by tenant '{tenant_id}'."
            )

        if load_relations:
            await self.session.refresh(portfolio, ["holdings", "risk_assessments"])

        return portfolio

    async def list_by_tenant(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Portfolio]:
        """Lists portfolios strictly for the authenticated tenant."""
        stmt = select(Portfolio).where(Portfolio.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Portfolio.is_deleted == False)  # noqa: E712

        stmt = stmt.order_by(Portfolio.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated(
        self,
        tenant_id: str,
        page_params: PageParams,
        include_deleted: bool = False,
    ) -> PagedResult[Portfolio]:
        """Returns paginated portfolio list with envelope."""
        stmt = select(Portfolio).where(Portfolio.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Portfolio.is_deleted == False)  # noqa: E712

        stmt = stmt.order_by(Portfolio.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)

    async def create(
        self,
        tenant_id: str,
        name: str,
        benchmark: str = "SPY",
        total_value: float = 0.0,
        positions_json: str = "[]",
        description: str = "",
        currency: str = "USD",
    ) -> Portfolio:
        """Creates portfolio strictly assigned to tenant."""
        portfolio = Portfolio(
            tenant_id=tenant_id,
            name=name,
            benchmark=benchmark,
            total_value=total_value,
            currency=currency,
            positions_json=positions_json,
            description=description,
            version=1,
            is_deleted=False,
        )
        self.session.add(portfolio)
        await self.session.commit()
        await self.session.refresh(portfolio)
        return portfolio

    async def add_holding(
        self,
        tenant_id: str,
        portfolio_id: str,
        ticker: str,
        shares: float,
        market_price: float,
        market_value: float,
        weight: float,
        cost_basis: float = 0.0,
        asset_class: str = "EQUITY",
    ) -> Holding:
        """Attaches an asset holding position to a portfolio."""
        await self.get_by_id(tenant_id=tenant_id, portfolio_id=portfolio_id, load_relations=False)
        holding = Holding(
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            ticker=ticker,
            shares=shares,
            market_price=market_price,
            market_value=market_value,
            weight=weight,
            cost_basis=cost_basis,
            asset_class=asset_class,
        )
        self.session.add(holding)
        await self.session.commit()
        await self.session.refresh(holding)
        return holding

    async def add_risk_assessment(
        self,
        tenant_id: str,
        portfolio_id: str,
        metric_value: float,
        assessment_type: str = "VAR",
        confidence_level: float = 0.99,
        horizon_days: int = 20,
        rating: str = "LOW",
        details_json: str = "{}",
        requires_hitl: bool = False,
    ) -> RiskAssessment:
        """Attaches a risk assessment output to a portfolio."""
        await self.get_by_id(tenant_id=tenant_id, portfolio_id=portfolio_id, load_relations=False)
        assessment = RiskAssessment(
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            assessment_type=assessment_type,
            confidence_level=confidence_level,
            horizon_days=horizon_days,
            metric_value=metric_value,
            rating=rating,
            details_json=details_json,
            requires_hitl=requires_hitl,
        )
        self.session.add(assessment)
        await self.session.commit()
        await self.session.refresh(assessment)
        return assessment

    async def update_with_optimistic_lock(
        self,
        tenant_id: str,
        portfolio_id: str,
        expected_version: int,
        total_value: float | None = None,
        description: str | None = None,
        name: str | None = None,
    ) -> Portfolio:
        """
        Updates portfolio metrics with optimistic concurrency control.
        Protects against race conditions in multi-trader rebalancing.
        """
        # Ensure portfolio exists and belongs to tenant
        await self.get_by_id(tenant_id=tenant_id, portfolio_id=portfolio_id)

        update_values: dict = {
            "version": Portfolio.version + 1,
            "updated_at": datetime.utcnow(),
        }
        if total_value is not None:
            update_values["total_value"] = total_value
        if description is not None:
            update_values["description"] = description
        if name is not None:
            update_values["name"] = name

        stmt = (
            update(Portfolio)
            .where(
                Portfolio.id == portfolio_id,
                Portfolio.tenant_id == tenant_id,
                Portfolio.version == expected_version,
                Portfolio.is_deleted == False,  # noqa: E712
            )
            .values(**update_values)
        )
        res = await self.session.execute(stmt)
        await self.session.commit()

        if getattr(res, "rowcount", 0) == 0:
            raise OptimisticConcurrencyException(
                entity_name="Portfolio",
                entity_id=portfolio_id,
                expected_version=expected_version,
            )

        return await self.get_by_id(tenant_id=tenant_id, portfolio_id=portfolio_id)

    async def soft_delete(self, tenant_id: str, portfolio_id: str) -> None:
        """Soft-deletes a portfolio."""
        portfolio = await self.get_by_id(tenant_id=tenant_id, portfolio_id=portfolio_id)
        portfolio.is_deleted = True
        portfolio.deleted_at = datetime.utcnow()
        await self.session.commit()
