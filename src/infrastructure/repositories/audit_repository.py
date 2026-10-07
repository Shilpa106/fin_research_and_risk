from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import AuditActionStatus, AuditEvent
from .pagination import PagedResult, PageParams, paginate_query


class AuditRepository:
    """
    Append-only repository for compliance audit events.
    Supports tenant-bounded forensic queries and pagination.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_event(
        self,
        tenant_id: str,
        action: str,
        resource_type: str,
        status: AuditActionStatus,
        user_id: str | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
        details: str | None = None,
    ) -> AuditEvent:
        """Appends an immutable audit event to the database."""
        event = AuditEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            ip_address=ip_address,
            request_id=request_id,
            details=details,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def list_paginated(
        self,
        tenant_id: str,
        page_params: PageParams,
        action: str | None = None,
        status: AuditActionStatus | None = None,
    ) -> PagedResult[AuditEvent]:
        """Returns paginated audit events for tenant."""
        stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditEvent.action == action)
        if status:
            stmt = stmt.where(AuditEvent.status == status)

        stmt = stmt.order_by(AuditEvent.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)
