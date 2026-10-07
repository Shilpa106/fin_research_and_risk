from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....application.dtos import (
    HITLActionRequest,
    HITLApprovalCreateRequest,
    HITLResolutionRequest,
    HITLTaskDetailDto,
    HITLTaskDto,
)
from ....application.services.hitl_service import HITLService
from ....domain.entities import HITLReviewStatus
from ....domain.exceptions import EntityNotFoundException
from ....infrastructure.database import get_db_session
from ....security.context import RequestSecurityContext
from ....security.guards import require_permissions

router = APIRouter(prefix="/hitl", tags=["Human-in-the-Loop Management"])


def _map_task_to_detail_dto(task) -> HITLTaskDetailDto:
    return HITLTaskDetailDto(
        id=task.id,
        task_id=task.id,
        tenant_id=task.tenant_id,
        user_id=task.user_id,
        thread_id=task.thread_id,
        agent_run_id=task.agent_run_id,
        trigger_reason=task.trigger_reason.value if hasattr(task.trigger_reason, "value") else str(task.trigger_reason),
        reason=task.reason,
        evidence=task.evidence or {},
        model_output=task.model_output or "",
        confidence=task.confidence,
        proposed_action=task.proposed_action,
        tool_calls=task.tool_calls or [],
        risk_score=task.risk_score,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        assigned_reviewer_id=task.assigned_reviewer_id,
        reviewed_by_id=task.reviewed_by_id,
        reviewed_at=task.reviewed_at,
        reviewer_decision_notes=task.reviewer_decision_notes,
        expires_at=task.expires_at,
        created_at=task.created_at,
        timestamp=task.created_at,
        version=task.version,
    )


@router.get("/tasks", response_model=list[HITLTaskDto], summary="List Pending HITL Review Tasks")
async def list_pending_tasks(
    context: RequestSecurityContext = Depends(require_permissions("hitl:review")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Returns tasks awaiting Senior Risk Officer review strictly bounded to caller tenant.
    Requires 'hitl:review' permission.
    """
    service = HITLService(session)
    tasks = await service.repository.list_tasks(
        tenant_id=context.tenant_id,
        status=HITLReviewStatus.PENDING,
    )
    return [
        HITLTaskDto(
            task_id=t.id,
            tenant_id=t.tenant_id,
            thread_id=t.thread_id,
            trigger_reason=t.trigger_reason.value if hasattr(t.trigger_reason, "value") else str(t.trigger_reason),
            risk_score=t.risk_score,
            status=t.status.value if hasattr(t.status, "value") else str(t.status),
            original_query=t.original_query or t.reason,
            generated_report_draft=t.generated_report_draft or t.model_output,
            created_at=t.created_at,
        )
        for t in tasks
    ]


@router.post("/tasks", response_model=HITLTaskDetailDto, summary="Create Approval Request")
async def create_approval_request(
    payload: HITLApprovalCreateRequest,
    context: RequestSecurityContext = Depends(require_permissions("conversations:write")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Creates an approval request for a high-risk financial operation.
    """
    service = HITLService(session)
    task = await service.create_approval_request(context=context, request=payload)
    return _map_task_to_detail_dto(task)


@router.get("/tasks/{task_id}", response_model=HITLTaskDetailDto, summary="Get HITL Task Details")
async def get_task_detail(
    task_id: str,
    context: RequestSecurityContext = Depends(require_permissions("hitl:review")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retrieves full details of an approval request, including evidence, model output, and proposed action.
    """
    service = HITLService(session)
    task = await service.repository.get_by_id(tenant_id=context.tenant_id, task_id=task_id)
    if not task:
        raise EntityNotFoundException("HITLReviewTask", task_id)
    return _map_task_to_detail_dto(task)


@router.post("/tasks/{task_id}/resolve", response_model=HITLTaskDetailDto, summary="Resolve Review Task")
async def resolve_task(
    task_id: str,
    resolution: HITLResolutionRequest,
    context: RequestSecurityContext = Depends(require_permissions("hitl:approve")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Approves, rejects, or cancels an approval request.
    Strictly enforced with RBAC and optimistic concurrency locking.
    """
    service = HITLService(session)
    task = await service.resolve_approval_request(
        context=context,
        task_id=task_id,
        resolution=resolution,
    )
    return _map_task_to_detail_dto(task)


@router.post("/tasks/{task_id}/action", summary="Submit Review Action (Legacy Compatible)")
async def review_task_action(
    task_id: str,
    action_request: HITLActionRequest,
    context: RequestSecurityContext = Depends(require_permissions("hitl:approve")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Backward-compatible review action endpoint.
    """
    service = HITLService(session)
    resolution = HITLResolutionRequest(
        action=action_request.action,
        decision_notes=action_request.reviewer_notes,
        modified_content=action_request.modified_content,
    )
    task = await service.resolve_approval_request(
        context=context,
        task_id=task_id,
        resolution=resolution,
    )
    return {
        "task_id": task.id,
        "action": action_request.action,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
        "tenant_id": task.tenant_id,
        "reviewed_by": task.reviewed_by_id,
        "version": task.version,
    }
