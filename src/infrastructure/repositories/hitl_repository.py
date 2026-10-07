from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import HITLReviewStatus, HITLReviewTask, HITLTriggerReason
from ...domain.exceptions import EntityNotFoundException, OptimisticConcurrencyException


class HITLRepository:
    """
    Transactional repository for Human-in-the-Loop review tasks.
    Enforces multi-tenant isolation, atomic resolution, and optimistic concurrency
    to prevent race conditions and duplicate approval processing.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_task(
        self,
        tenant_id: str,
        reason: str,
        evidence: dict[str, Any] | list[Any],
        model_output: str,
        confidence: float,
        proposed_action: str,
        user_id: str | None = None,
        thread_id: str = "default-thread",
        agent_run_id: str | None = None,
        tool_calls: list[Any] | None = None,
        risk_score: float | None = None,
        trigger_reason: HITLTriggerReason = HITLTriggerReason.HIGH_RISK_THRESHOLD,
        expires_at: datetime | None = None,
    ) -> HITLReviewTask:
        """Creates a new PENDING approval request task."""
        task = HITLReviewTask(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
            agent_run_id=agent_run_id,
            trigger_reason=trigger_reason,
            reason=reason,
            evidence=evidence,
            model_output=model_output,
            confidence=confidence,
            proposed_action=proposed_action,
            tool_calls=tool_calls or [],
            risk_score=risk_score,
            status=HITLReviewStatus.PENDING,
            expires_at=expires_at,
            original_query=reason,
            generated_report_draft=model_output,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def get_by_id(self, tenant_id: str, task_id: str) -> HITLReviewTask | None:
        """Retrieves a review task strictly within the caller tenant boundary."""
        stmt = select(HITLReviewTask).where(
            HITLReviewTask.tenant_id == tenant_id,
            HITLReviewTask.id == task_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_tasks(
        self,
        tenant_id: str,
        status: HITLReviewStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[HITLReviewTask]:
        """Lists review tasks for a tenant with optional status filtering."""
        stmt = (
            select(HITLReviewTask)
            .where(HITLReviewTask.tenant_id == tenant_id)
            .order_by(HITLReviewTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(HITLReviewTask.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def atomic_resolve_task(
        self,
        tenant_id: str,
        task_id: str,
        expected_version: int,
        new_status: HITLReviewStatus,
        reviewer_id: str,
        notes: str | None = None,
    ) -> HITLReviewTask:
        """
        Atomically updates task status with optimistic locking.
        Prevents race conditions and duplicate approvals across concurrent reviewers.
        """
        now = datetime.utcnow()
        stmt = (
            update(HITLReviewTask)
            .where(
                HITLReviewTask.id == task_id,
                HITLReviewTask.tenant_id == tenant_id,
                HITLReviewTask.version == expected_version,
                HITLReviewTask.status == HITLReviewStatus.PENDING,
            )
            .values(
                status=new_status,
                reviewed_by_id=reviewer_id,
                reviewed_at=now,
                reviewer_decision_notes=notes,
                version=HITLReviewTask.version + 1,
            )
        )
        res = await self.session.execute(stmt)
        rowcount = getattr(res, "rowcount", 0)

        if rowcount == 0:
            task = await self.get_by_id(tenant_id, task_id)
            if not task:
                raise EntityNotFoundException("HITLReviewTask", task_id)
            if task.status != HITLReviewStatus.PENDING:
                raise OptimisticConcurrencyException(
                    entity_name="HITLReviewTask",
                    entity_id=task_id,
                    expected_version=expected_version,
                    message=(
                        f"Duplicate approval prevented: Task '{task_id}' has already been resolved "
                        f"with status '{task.status.value}'."
                    ),
                )
            raise OptimisticConcurrencyException(
                entity_name="HITLReviewTask",
                entity_id=task_id,
                expected_version=expected_version,
                message=f"Concurrent update conflict: Task '{task_id}' was modified by another reviewer transaction.",
            )

        await self.session.commit()
        updated_task = await self.get_by_id(tenant_id, task_id)
        if not updated_task:
            raise EntityNotFoundException("HITLReviewTask", task_id)
        return updated_task

    async def expire_stale_tasks(self, tenant_id: str) -> int:
        """Batch expires tasks that have surpassed their SLA expiration timestamp."""
        now = datetime.utcnow()
        stmt = (
            update(HITLReviewTask)
            .where(
                HITLReviewTask.tenant_id == tenant_id,
                HITLReviewTask.status == HITLReviewStatus.PENDING,
                HITLReviewTask.expires_at.is_not(None),
                HITLReviewTask.expires_at <= now,
            )
            .values(
                status=HITLReviewStatus.EXPIRED,
                reviewer_decision_notes="Expired due to SLA timeout without reviewer action.",
                version=HITLReviewTask.version + 1,
            )
        )
        res = await self.session.execute(stmt)
        await self.session.commit()
        return int(getattr(res, "rowcount", 0))
