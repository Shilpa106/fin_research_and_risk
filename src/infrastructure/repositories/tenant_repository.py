from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Tenant, TenantTier
from ...domain.exceptions import EntityNotFoundException
from .pagination import PagedResult, PageParams, paginate_query


class TenantRepository:
    """Repository for managing Tenant boundaries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, tenant_id: str, include_deleted: bool = False) -> Tenant:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Tenant.is_deleted == False)  # noqa: E712
        res = await self.session.execute(stmt)
        tenant = res.scalar_one_or_none()
        if not tenant:
            raise EntityNotFoundException("Tenant", tenant_id)
        return tenant

    async def get_by_slug(self, slug: str, include_deleted: bool = False) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.slug == slug)
        if not include_deleted:
            stmt = stmt.where(Tenant.is_deleted == False)  # noqa: E712
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create(
        self,
        name: str,
        slug: str,
        tier: TenantTier = TenantTier.ENTERPRISE,
        max_rate_limit_rps: int = 2000,
        hitl_threshold_var: float = 0.05,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            slug=slug,
            tier=tier,
            max_rate_limit_rps=max_rate_limit_rps,
            hitl_threshold_var=hitl_threshold_var,
            is_active=True,
            is_deleted=False,
        )
        self.session.add(tenant)
        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def list_paginated(self, page_params: PageParams, include_deleted: bool = False) -> PagedResult[Tenant]:
        stmt = select(Tenant)
        if not include_deleted:
            stmt = stmt.where(Tenant.is_deleted == False)  # noqa: E712
        stmt = stmt.order_by(Tenant.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)

    async def soft_delete(self, tenant_id: str) -> None:
        tenant = await self.get_by_id(tenant_id)
        tenant.is_deleted = True
        tenant.deleted_at = datetime.utcnow()
        await self.session.commit()
