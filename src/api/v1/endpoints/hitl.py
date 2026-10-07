from fastapi import APIRouter, Depends

from ....application.dtos import HITLActionRequest, HITLTaskDto
from ....security.context import RequestSecurityContext
from ....security.guards import require_permissions

router = APIRouter(prefix="/hitl", tags=["Human-in-the-Loop Management"])


@router.get("/tasks", response_model=list[HITLTaskDto], summary="List Pending HITL Review Tasks")
async def list_pending_tasks(
    context: RequestSecurityContext = Depends(require_permissions("hitl:review")),
):
    """
    Returns tasks awaiting Senior Risk Officer review.
    Requires 'hitl:review' permission.
    """
    return []


@router.post("/tasks/{task_id}/action", summary="Submit Review Action")
async def review_task_action(
    task_id: str,
    action_request: HITLActionRequest,
    context: RequestSecurityContext = Depends(require_permissions("hitl:approve")),
):
    """
    Approves, rejects, or modifies an interrupted report.
    Requires 'hitl:approve' permission.
    """
    return {
        "task_id": task_id,
        "action": action_request.action,
        "status": "RESOLVED",
        "tenant_id": context.tenant_id,
        "reviewed_by": context.user_id,
    }

