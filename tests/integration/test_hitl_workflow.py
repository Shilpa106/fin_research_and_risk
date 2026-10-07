from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.orchestrator import AgentOrchestrator
from src.agents.state import ValidationStatus
from src.application.dtos import (
    HITLApprovalCreateRequest,
    HITLResolutionRequest,
)
from src.application.services.hitl_notification_service import HITLNotificationService
from src.application.services.hitl_service import HITLService
from src.domain.entities import (
    AuditEvent,
    HITLReviewStatus,
    RoleType,
)
from src.domain.exceptions import (
    AuthorizationException,
    EntityNotFoundException,
    HITLInterruptException,
    OptimisticConcurrencyException,
)
from src.security.context import RequestSecurityContext

# ==============================================================================
# Test Fixtures
# ==============================================================================

@pytest.fixture
def risk_manager_context() -> RequestSecurityContext:
    return RequestSecurityContext(
        tenant_id="tenant-hitl-001",
        user_id="user-risk-officer-99",
        roles=[RoleType.RISK_MANAGER],
        permissions={"hitl:review", "hitl:approve", "risk:execute", "conversations:write"},
        request_id="req-risk-001",
        client_ip="192.168.1.50",
        email="chief.risk@enterprise.bank",
    )


@pytest.fixture
def admin_context() -> RequestSecurityContext:
    return RequestSecurityContext(
        tenant_id="tenant-hitl-001",
        user_id="user-admin-01",
        roles=[RoleType.ADMIN],
        permissions={"*"},
        request_id="req-admin-001",
        client_ip="192.168.1.10",
        email="admin@enterprise.bank",
    )


@pytest.fixture
def analyst_context() -> RequestSecurityContext:
    return RequestSecurityContext(
        tenant_id="tenant-hitl-001",
        user_id="user-analyst-02",
        roles=[RoleType.ANALYST],
        permissions={"conversations:read", "conversations:write", "risk:execute", "hitl:review"},
        request_id="req-analyst-001",
        client_ip="192.168.1.80",
        email="analyst@enterprise.bank",
    )


@pytest.fixture
def read_only_context() -> RequestSecurityContext:
    return RequestSecurityContext(
        tenant_id="tenant-hitl-001",
        user_id="user-readonly-03",
        roles=[RoleType.READ_ONLY_USER],
        permissions={"conversations:read"},
        request_id="req-ro-001",
        client_ip="192.168.1.99",
        email="auditor@enterprise.bank",
    )


@pytest.fixture
def other_tenant_context() -> RequestSecurityContext:
    return RequestSecurityContext(
        tenant_id="tenant-external-999",
        user_id="user-other-01",
        roles=[RoleType.RISK_MANAGER],
        permissions={"hitl:review", "hitl:approve"},
        request_id="req-other-001",
        client_ip="10.50.0.1",
        email="risk@other.bank",
    )


# ==============================================================================
# 1. APPROVAL REQUEST CREATION & CONTENTS VERIFICATION
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_approval_request_contains_all_required_attributes(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
):
    """
    Verify approval request contains: reason, evidence, model output, confidence,
    proposed action, user, tenant, timestamp, agent run, and tool calls.
    """
    notification_svc = HITLNotificationService()
    service = HITLService(session=async_db_session, notification_service=notification_svc)

    evidence_data = {
        "portfolio_id": "port-tech-growth",
        "var_99_1d": 0.0825,
        "var_threshold": 0.0500,
        "concentrated_positions": [{"ticker": "NVDA", "weight": 0.42}],
    }
    tool_calls_data = [
        {"tool": "calculate_exposure", "arguments": {"ticker": "NVDA"}, "result": {"exposure": 0.42}},
        {"tool": "portfolio_var_simulator", "arguments": {"confidence": 0.99}, "result": {"var": 0.0825}},
    ]

    create_dto = HITLApprovalCreateRequest(
        reason="1-Day 99% VaR of 8.25% breached tenant risk limit of 5.00%",
        evidence=evidence_data,
        model_output="AI proposes reducing NVDA holding by 15% to restore risk compliance.",
        confidence=0.96,
        proposed_action="liquidate_position",
        tool_calls=tool_calls_data,
        risk_score=8.25,
        thread_id="thread-portfolio-var-777",
        agent_run_id="run-risk-agent-12345",
    )

    task = await service.create_approval_request(context=analyst_context, request=create_dto)

    # 1. Verify all required attributes are present and match
    assert task.id is not None
    assert task.tenant_id == analyst_context.tenant_id
    assert task.user_id == analyst_context.user_id
    assert task.reason == create_dto.reason
    assert task.evidence == evidence_data
    assert task.model_output == create_dto.model_output
    assert task.confidence == 0.96
    assert task.proposed_action == "liquidate_position"
    assert task.tool_calls == tool_calls_data
    assert task.risk_score == 8.25
    assert task.thread_id == "thread-portfolio-var-777"
    assert task.agent_run_id == "run-risk-agent-12345"
    assert task.status == HITLReviewStatus.PENDING
    assert task.created_at is not None
    assert isinstance(task.created_at, datetime)
    assert task.version == 1

    # 2. Verify reviewer notification was dispatched
    notifications = notification_svc.get_dispatched_notifications(tenant_id=analyst_context.tenant_id)
    assert len(notifications) == 1
    assert notifications[0]["task_id"] == task.id
    assert "RISK_MANAGER" in notifications[0]["target_roles"]

    # 3. Verify immutable security audit event logged
    audit_stmt = select(AuditEvent).where(
        AuditEvent.resource_id == task.id,
        AuditEvent.action == "HITL_APPROVAL_REQUEST_CREATED",
    )
    audit_res = await async_db_session.execute(audit_stmt)
    audit_entry = audit_res.scalar_one_or_none()
    assert audit_entry is not None
    assert audit_entry.tenant_id == analyst_context.tenant_id
    assert audit_entry.user_id == analyst_context.user_id


# ==============================================================================
# 2. LIFECYCLE STATUSES: PENDING -> APPROVED / REJECTED / CANCELLED / EXPIRED
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_approval_lifecycle_approved(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    risk_manager_context: RequestSecurityContext,
):
    """Test full approval lifecycle from PENDING to APPROVED."""
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="Leverage exceeded 2.5x threshold",
        evidence={"current_leverage": 2.8},
        model_output="Approve collateral injection of $500,000",
        proposed_action="rebalance_portfolio",
    )
    task = await service.create_approval_request(analyst_context, create_dto)
    assert task.status == HITLReviewStatus.PENDING

    # Reviewer approves
    resolution = HITLResolutionRequest(
        action="APPROVED",
        decision_notes="Collateral transfer verified with treasury; approved.",
    )
    resolved_task = await service.resolve_approval_request(risk_manager_context, task.id, resolution)

    assert resolved_task.status == HITLReviewStatus.APPROVED
    assert resolved_task.reviewed_by_id == risk_manager_context.user_id
    assert resolved_task.reviewed_at is not None
    assert resolved_task.reviewer_decision_notes == "Collateral transfer verified with treasury; approved."
    assert resolved_task.version == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_approval_lifecycle_rejected(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    risk_manager_context: RequestSecurityContext,
):
    """Test rejection lifecycle from PENDING to REJECTED."""
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="High concentration in volatile asset",
        evidence={"ticker": "TSLA", "concentration": 0.35},
        model_output="Increase TSLA allocation",
        proposed_action="override_risk_limit",
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    # Risk Manager rejects
    resolution = HITLResolutionRequest(
        action="REJECTED",
        decision_notes="Exceeds mandate concentration policy; trade rejected.",
    )
    resolved_task = await service.resolve_approval_request(risk_manager_context, task.id, resolution)

    assert resolved_task.status == HITLReviewStatus.REJECTED
    assert resolved_task.reviewed_by_id == risk_manager_context.user_id
    assert resolved_task.version == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_approval_lifecycle_cancelled(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
):
    """Test cancellation lifecycle from PENDING to CANCELLED."""
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="Accidental duplicate VaR rebalance trigger",
        evidence={},
        model_output="N/A",
        proposed_action="cancel_trade",
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    # Initiating analyst cancels own request
    cancelled_task = await service.cancel_approval_request(analyst_context, task.id, "Analyst retracted calculation")
    assert cancelled_task.status == HITLReviewStatus.CANCELLED
    assert cancelled_task.reviewer_decision_notes == "Analyst retracted calculation"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_approval_lifecycle_expired(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    risk_manager_context: RequestSecurityContext,
):
    """Test SLA expiration: requests past expires_at cannot be approved and transition to EXPIRED."""
    service = HITLService(session=async_db_session)

    # Create task with short expiration and backdate expires_at
    create_dto = HITLApprovalCreateRequest(
        reason="Time-sensitive block trade pre-approval",
        evidence={},
        model_output="Execute block trade",
        proposed_action="execute_block_trade",
        expires_in_seconds=1,
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    # Artificially set expires_at in the past
    task.expires_at = datetime.utcnow() - timedelta(minutes=5)
    await async_db_session.commit()

    # Attempting to resolve expired task must fail
    resolution = HITLResolutionRequest(action="APPROVED", decision_notes="Approving late")
    with pytest.raises(OptimisticConcurrencyException) as exc_info:
        await service.resolve_approval_request(risk_manager_context, task.id, resolution)
    assert "expired" in str(exc_info.value).lower()

    # Verify task state is EXPIRED
    refreshed_task = await service.repository.get_by_id(analyst_context.tenant_id, task.id)
    assert refreshed_task.status == HITLReviewStatus.EXPIRED


# ==============================================================================
# 3. AUTHORIZATION: ONLY AUTHORIZED ROLES CAN APPROVE
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_unauthorized_roles_cannot_approve(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    read_only_context: RequestSecurityContext,
):
    """
    Verify that users with ANALYST or READ_ONLY_USER roles without 'hitl:approve'
    are strictly rejected from approving or rejecting tasks.
    """
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="VaR breach",
        evidence={},
        model_output="Rebalance",
        proposed_action="rebalance_portfolio",
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    resolution = HITLResolutionRequest(action="APPROVED")

    # 1. Analyst attempting self-approval or unauthorized approval
    with pytest.raises(AuthorizationException) as exc_analyst:
        await service.resolve_approval_request(analyst_context, task.id, resolution)
    assert "Unauthorized" in str(exc_analyst.value)

    # 2. Read-Only user attempting approval
    with pytest.raises(AuthorizationException) as exc_ro:
        await service.resolve_approval_request(read_only_context, task.id, resolution)
    assert "Unauthorized" in str(exc_ro.value)

    # Verify audit event for denied unauthorized attempt
    stmt = select(AuditEvent).where(
        AuditEvent.resource_id == task.id,
        AuditEvent.action == "HITL_UNAUTHORIZED_RESOLUTION_ATTEMPT",
    )
    audit_res = await async_db_session.execute(stmt)
    assert len(list(audit_res.scalars().all())) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_tenant_approval_isolation(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    other_tenant_context: RequestSecurityContext,
):
    """Verify reviewer from Tenant B cannot approve a task belonging to Tenant A."""
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="Tenant Alpha confidential risk alert",
        evidence={},
        model_output="Liquidate",
        proposed_action="liquidate_holdings",
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    # Other tenant reviewer attempting approval on Tenant Alpha's task
    with pytest.raises(EntityNotFoundException):
        await service.resolve_approval_request(
            other_tenant_context,
            task.id,
            HITLResolutionRequest(action="APPROVED"),
        )


# ==============================================================================
# 4. DUPLICATE APPROVAL PREVENTION & RACE CONDITIONS DEFENSE
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_approval_prevention(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    risk_manager_context: RequestSecurityContext,
):
    """
    Verify that resolving an already-resolved task is strictly rejected.
    """
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="Stress test failure",
        evidence={},
        model_output="Reduce exposure",
        proposed_action="reduce_exposure",
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    # Initial approval succeeds
    resolution = HITLResolutionRequest(action="APPROVED", decision_notes="First approval")
    await service.resolve_approval_request(risk_manager_context, task.id, resolution)

    # Second approval attempt must fail
    with pytest.raises(OptimisticConcurrencyException) as exc_dup:
        await service.resolve_approval_request(risk_manager_context, task.id, resolution)
    assert "Duplicate approval prevented" in str(exc_dup.value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_race_conditions_concurrent_approval_resolution(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    risk_manager_context: RequestSecurityContext,
    admin_context: RequestSecurityContext,
):
    """
    Simulate two reviewers attempting to resolve the same task simultaneously.
    Optimistic locking ensures exactly ONE reviewer succeeds and the other receives a conflict.
    """
    service = HITLService(session=async_db_session)
    create_dto = HITLApprovalCreateRequest(
        reason="Concurrent trade approval test",
        evidence={"metric": 42},
        model_output="Execute hedge",
        proposed_action="execute_hedge",
    )
    task = await service.create_approval_request(analyst_context, create_dto)

    resolution_rm = HITLResolutionRequest(action="APPROVED", decision_notes="Risk Manager approval")
    resolution_admin = HITLResolutionRequest(action="REJECTED", decision_notes="Admin override reject")

    # Sequentially / concurrently invoke with fresh snapshots
    # Service 1 resolves
    await service.resolve_approval_request(risk_manager_context, task.id, resolution_rm)

    # Service 2 attempting concurrent resolve on same initial task version must fail
    with pytest.raises(OptimisticConcurrencyException):
        await service.resolve_approval_request(admin_context, task.id, resolution_admin)

    # Confirm final status is the winning first resolution
    final_task = await service.repository.get_by_id(analyst_context.tenant_id, task.id)
    assert final_task.status == HITLReviewStatus.APPROVED
    assert final_task.reviewed_by_id == risk_manager_context.user_id
    assert final_task.version == 2


# ==============================================================================
# 5. END-TO-END WORKFLOW: AI RISK DETECTION -> PAUSE -> NOTIFY -> APPROVE -> RESUME
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_hitl_workflow_interception_and_resume(
    async_db_session: AsyncSession,
    analyst_context: RequestSecurityContext,
    risk_manager_context: RequestSecurityContext,
):
    """
    Full financial workflow test:
    1. AI detects risk score > configured threshold (e.g. 7.5 > 5.0).
    2. HITLService intercepts and raises HITLInterruptException.
    3. Workflow pauses with HUMAN_APPROVAL_REQUIRED state.
    4. Reviewer receives notification and approves.
    5. AgentOrchestrator resumes workflow from checkpoint to completion.
    """
    service = HITLService(session=async_db_session)
    orchestrator = AgentOrchestrator()
    thread_id = "thread-portfolio-stress-test-99"

    # 1. Run agent orchestration step that creates checkpoint
    state = await orchestrator.run(
        user_request="Simulate 200bps rate shock on Treasury book",
        tenant_id=analyst_context.tenant_id,
        thread_id=thread_id,
    )
    assert state is not None

    # 2. Risk check evaluates portfolio VaR of 7.85 breaching threshold 5.00
    risk_score = 7.85
    configured_threshold = 5.00

    task_id = None
    try:
        await service.evaluate_risk_and_intercept(
            context=analyst_context,
            risk_score=risk_score,
            threshold=configured_threshold,
            proposed_action="liquidate_treasury_derivatives",
            evidence={"duration_gap": 4.2, "var_breach_pct": 0.0785},
            model_output="Recommend liquidation of $20M 10Y futures to stabilize duration.",
            thread_id=thread_id,
        )
    except HITLInterruptException as hitl_interrupt:
        task_id = hitl_interrupt.details["hitl_task_id"]
        assert hitl_interrupt.status_code == 202
        assert "breached configured threshold" in hitl_interrupt.details["trigger_reason"]

    assert task_id is not None

    # 3. Verify task is pending
    task = await service.repository.get_by_id(analyst_context.tenant_id, task_id)
    assert task.status == HITLReviewStatus.PENDING

    # 4. Reviewer approves
    resolution = HITLResolutionRequest(action="APPROVED", decision_notes="Approved liquidation of futures")
    resolved_task = await service.resolve_approval_request(risk_manager_context, task_id, resolution)
    assert resolved_task.status == HITLReviewStatus.APPROVED

    # 5. Resume paused workflow in AgentOrchestrator
    resumed_state = await orchestrator.resume_workflow(
        thread_id=thread_id,
        approval_decision="APPROVED",
        reviewer_notes="Approved liquidation of futures",
    )
    assert resumed_state["validation_status"] == ValidationStatus.APPROVED.value
    assert "Human Approval Granted" in resumed_state["final_response"]


# ==============================================================================
# 6. REST API ENDPOINTS: /api/v1/hitl/tasks
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_api_endpoints_flow(test_client: AsyncClient):
    """
    Test REST API flow for HITL management:
    - POST /api/v1/hitl/tasks: create request
    - GET /api/v1/hitl/tasks: list pending tasks
    - GET /api/v1/hitl/tasks/{task_id}: get detail
    - POST /api/v1/hitl/tasks/{task_id}/resolve: approve
    """
    tenant_hdr = {"X-Tenant-ID": "tenant-test-uuid-123"}

    # 1. Create approval request
    create_payload = {
        "reason": "VaR calculation 6.5% breaches 5.0% threshold",
        "evidence": {"var": 0.065},
        "model_output": "Liquidate position",
        "confidence": 0.94,
        "proposed_action": "liquidate_holdings",
        "risk_score": 6.5,
    }
    create_res = await test_client.post("/api/v1/hitl/tasks", headers=tenant_hdr, json=create_payload)
    assert create_res.status_code == 200
    created_data = create_res.json()
    task_id = created_data["id"]
    assert created_data["status"] == "PENDING"
    assert created_data["confidence"] == 0.94
    assert created_data["proposed_action"] == "liquidate_holdings"

    # 2. List pending tasks
    list_res = await test_client.get("/api/v1/hitl/tasks", headers=tenant_hdr)
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert any(t["task_id"] == task_id for t in tasks)

    # 3. Get task detail
    detail_res = await test_client.get(f"/api/v1/hitl/tasks/{task_id}", headers=tenant_hdr)
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["reason"] == create_payload["reason"]
    assert detail_data["evidence"] == create_payload["evidence"]

    # 4. Resolve task (Approve)
    resolve_payload = {
        "action": "APPROVED",
        "decision_notes": "Approved by senior risk officer via API",
    }
    resolve_res = await test_client.post(
        f"/api/v1/hitl/tasks/{task_id}/resolve",
        headers=tenant_hdr,
        json=resolve_payload,
    )
    assert resolve_res.status_code == 200
    resolved_data = resolve_res.json()
    assert resolved_data["status"] == "APPROVED"
    assert resolved_data["reviewer_decision_notes"] == "Approved by senior risk officer via API"
    assert resolved_data["version"] == 2
