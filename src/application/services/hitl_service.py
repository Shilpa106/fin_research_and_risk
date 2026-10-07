from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import (
    AuditActionStatus,
    HITLReviewStatus,
    HITLReviewTask,
    HITLTriggerReason,
    RoleType,
)
from ...domain.exceptions import (
    AuthorizationException,
    EntityNotFoundException,
    HITLInterruptException,
    OptimisticConcurrencyException,
)
from ...infrastructure.repositories.hitl_repository import HITLRepository
from ...security.audit import record_security_audit_event
from ...security.context import RequestSecurityContext
from ..dtos import HITLApprovalCreateRequest, HITLResolutionRequest
from .hitl_notification_service import HITLNotificationService


class HITLService:
    """
    Enterprise Human-in-the-Loop Workflow Service.
    Orchestrates the complete lifecycle of high-impact financial approvals:
    1. Interception and approval request creation on risk threshold breach
    2. Reviewer notification dispatch
    3. Strict RBAC approval authorization (RISK_MANAGER, ADMIN)
    4. Immutable audit logging of all review events
    5. Race condition prevention via atomic optimistic concurrency
    6. Workflow pause and resume integration
    """

    # Roles explicitly authorized to approve or reject financial operations
    AUTHORIZED_APPROVER_ROLES: set[RoleType] = {
        RoleType.RISK_MANAGER,
        RoleType.ADMIN,
    }

    def __init__(
        self,
        session: AsyncSession,
        notification_service: HITLNotificationService | None = None,
    ):
        self.session = session
        self.repository = HITLRepository(session)
        self.notification_service = notification_service or HITLNotificationService()

    async def create_approval_request(
        self,
        context: RequestSecurityContext,
        request: HITLApprovalCreateRequest,
    ) -> HITLReviewTask:
        """
        Creates a new PENDING approval request, notifies reviewers, and logs an audit event.
        """
        expires_at = None
        if request.expires_in_seconds:
            expires_at = datetime.utcnow() + timedelta(seconds=request.expires_in_seconds)

        task = await self.repository.create_task(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            thread_id=request.thread_id or "default-thread",
            agent_run_id=request.agent_run_id,
            reason=request.reason,
            evidence=request.evidence,
            model_output=request.model_output,
            confidence=request.confidence,
            proposed_action=request.proposed_action,
            tool_calls=request.tool_calls,
            risk_score=request.risk_score,
            trigger_reason=HITLTriggerReason.HIGH_RISK_THRESHOLD,
            expires_at=expires_at,
        )

        # Notify authorized reviewers
        await self.notification_service.notify_reviewers(
            task=task,
            target_roles=list(self.AUTHORIZED_APPROVER_ROLES),
        )

        # Immutable security audit entry
        await record_security_audit_event(
            session=self.session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            action="HITL_APPROVAL_REQUEST_CREATED",
            status=AuditActionStatus.SUCCESS,
            resource_type="HITL_TASK",
            resource_id=task.id,
            ip_address=context.client_ip,
            request_id=context.request_id,
            details={
                "reason": request.reason,
                "proposed_action": request.proposed_action,
                "risk_score": request.risk_score,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )

        return task

    async def resolve_approval_request(
        self,
        context: RequestSecurityContext,
        task_id: str,
        resolution: HITLResolutionRequest,
    ) -> HITLReviewTask:
        """
        Resolves an approval request (APPROVED | REJECTED | CANCELLED).
        Strictly enforces:
        - Role authorization (only RISK_MANAGER or ADMIN)
        - Tenant boundary isolation
        - Non-duplicate processing & atomic version check
        - Expiration checking
        """
        # 1. Authorization Gate: Only authorized roles or users with 'hitl:approve' can resolve
        is_authorized_role = any(r in self.AUTHORIZED_APPROVER_ROLES for r in context.roles)
        has_approve_perm = context.has_permission("hitl:approve")
        if not (is_authorized_role or has_approve_perm):
            await record_security_audit_event(
                session=self.session,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                action="HITL_UNAUTHORIZED_RESOLUTION_ATTEMPT",
                status=AuditActionStatus.DENIED,
                resource_type="HITL_TASK",
                resource_id=task_id,
                ip_address=context.client_ip,
                request_id=context.request_id,
                details={"roles": [r.value for r in context.roles]},
            )
            raise AuthorizationException(
                f"Unauthorized: User lacks required role ({[r.value for r in self.AUTHORIZED_APPROVER_ROLES]}) "
                "or 'hitl:approve' permission to resolve approval requests."
            )

        # 2. Retrieve existing task bounded to tenant
        task = await self.repository.get_by_id(context.tenant_id, task_id)
        if not task:
            raise EntityNotFoundException("HITLReviewTask", task_id)

        # 3. Check for Duplicate Approval Processing
        if task.status != HITLReviewStatus.PENDING:
            raise OptimisticConcurrencyException(
                entity_name="HITLReviewTask",
                entity_id=task_id,
                expected_version=task.version,
                message=(
                    f"Duplicate approval prevented: Task '{task_id}' has already been processed "
                    f"with terminal status '{task.status.value}'."
                ),
            )

        # 4. Check for SLA Expiration
        now = datetime.utcnow()
        if task.expires_at and task.expires_at <= now:
            await self.repository.atomic_resolve_task(
                tenant_id=context.tenant_id,
                task_id=task_id,
                expected_version=task.version,
                new_status=HITLReviewStatus.EXPIRED,
                reviewer_id=context.user_id,
                notes="Task expired prior to reviewer action.",
            )
            await record_security_audit_event(
                session=self.session,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                action="HITL_TASK_EXPIRED",
                status=AuditActionStatus.FAILED,
                resource_type="HITL_TASK",
                resource_id=task_id,
                ip_address=context.client_ip,
                request_id=context.request_id,
            )
            raise OptimisticConcurrencyException(
                entity_name="HITLReviewTask",
                entity_id=task_id,
                expected_version=task.version,
                message=f"Action rejected: Task '{task_id}' expired on {task.expires_at.isoformat()}.",
            )

        # 5. Normalize Target Status
        action_clean = resolution.action.upper()
        if action_clean in {"APPROVED", "APPROVE"}:
            target_status = HITLReviewStatus.APPROVED
        elif action_clean in {"REJECTED", "REJECT"}:
            target_status = HITLReviewStatus.REJECTED
        elif action_clean in {"CANCELLED", "CANCEL"}:
            target_status = HITLReviewStatus.CANCELLED
        else:
            target_status = HITLReviewStatus.APPROVED

        # 6. Atomic Resolution with Optimistic Locking
        updated_task = await self.repository.atomic_resolve_task(
            tenant_id=context.tenant_id,
            task_id=task_id,
            expected_version=task.version,
            new_status=target_status,
            reviewer_id=context.user_id,
            notes=resolution.decision_notes,
        )

        # 7. Immutable Security Audit Logging
        await record_security_audit_event(
            session=self.session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            action=f"HITL_APPROVAL_{target_status.value}",
            status=AuditActionStatus.SUCCESS,
            resource_type="HITL_TASK",
            resource_id=task_id,
            ip_address=context.client_ip,
            request_id=context.request_id,
            details={
                "previous_status": task.status.value,
                "new_status": target_status.value,
                "reviewer_id": context.user_id,
                "notes": resolution.decision_notes,
            },
        )

        return updated_task

    async def cancel_approval_request(
        self,
        context: RequestSecurityContext,
        task_id: str,
        reason: str = "User cancelled request",
    ) -> HITLReviewTask:
        """Cancels a pending approval request."""
        task = await self.repository.get_by_id(context.tenant_id, task_id)
        if not task:
            raise EntityNotFoundException("HITLReviewTask", task_id)

        # Only creator or Admin/Risk Manager can cancel
        is_creator = task.user_id == context.user_id
        is_admin_or_risk = any(r in self.AUTHORIZED_APPROVER_ROLES for r in context.roles)
        if not (is_creator or is_admin_or_risk):
            raise AuthorizationException("Only the original requester or an Administrator may cancel this request.")

        # Temporarily grant authorization if creator is cancelling own request
        return await self.repository.atomic_resolve_task(
            tenant_id=context.tenant_id,
            task_id=task_id,
            expected_version=task.version,
            new_status=HITLReviewStatus.CANCELLED,
            reviewer_id=context.user_id,
            notes=reason,
        )

    async def evaluate_risk_and_intercept(
        self,
        context: RequestSecurityContext,
        risk_score: float,
        threshold: float,
        proposed_action: str,
        evidence: dict[str, Any] | list[Any],
        model_output: str,
        confidence: float = 0.95,
        thread_id: str = "default-thread",
        agent_run_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> HITLReviewTask | None:
        """
        Core financial safety interceptor:
        If risk score > threshold:
        1. Creates approval request
        2. Raises HITLInterruptException to halt execution
        """
        if risk_score > threshold:
            reason = (
                f"Quantitative risk score ({risk_score:.2f}) breached configured threshold ({threshold:.2f}) "
                f"for proposed action '{proposed_action}'."
            )
            create_dto = HITLApprovalCreateRequest(
                reason=reason,
                evidence=evidence,
                model_output=model_output,
                confidence=confidence,
                proposed_action=proposed_action,
                tool_calls=tool_calls or [],
                risk_score=risk_score,
                thread_id=thread_id,
                agent_run_id=agent_run_id,
            )
            task = await self.create_approval_request(context=context, request=create_dto)
            raise HITLInterruptException(task_id=task.id, reason=reason)

        return None
