import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.domain.entities import (
    AuditActionStatus,
    DocumentType,
    FinancialDocument,
    HITLReviewStatus,
    HITLReviewTask,
    HITLTriggerReason,
    IngestionStatus,
    Role,
    RoleType,
    SecurityAuditEvent,
    Tenant,
    TenantMembership,
    User,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_and_user_creation(async_db_session: AsyncSession, sample_tenant: Tenant):
    """Verify tenant persistence, user, and tenant membership with RBAC role."""
    user = User(
        email="risk_officer@msam.com",
        hashed_password="mock_hashed_password",
        full_name="Chief Risk Officer",
    )
    async_db_session.add(user)
    await async_db_session.flush()

    role = Role(
        name=RoleType.RISK_MANAGER,
        description="Institutional Risk Management Officer",
    )
    async_db_session.add(role)
    await async_db_session.flush()

    membership = TenantMembership(
        tenant_id=sample_tenant.id,
        user_id=user.id,
        is_active=True,
    )
    membership.roles.append(role)
    async_db_session.add(membership)
    await async_db_session.commit()

    stmt = (
        select(User)
        .options(selectinload(User.memberships).selectinload(TenantMembership.roles))
        .where(User.email == "risk_officer@msam.com")
    )
    result = await async_db_session.execute(stmt)
    retrieved_user = result.scalar_one_or_none()

    assert retrieved_user is not None
    assert retrieved_user.email == "risk_officer@msam.com"
    assert len(retrieved_user.memberships) == 1
    assert retrieved_user.memberships[0].tenant_id == sample_tenant.id
    assert retrieved_user.memberships[0].roles[0].name == RoleType.RISK_MANAGER


@pytest.mark.unit
@pytest.mark.asyncio
async def test_financial_document_creation(async_db_session: AsyncSession, sample_tenant: Tenant):
    """Verify financial document cataloging with content deduplication hash."""
    doc = FinancialDocument(
        tenant_id=sample_tenant.id,
        ticker="MSFT",
        company_name="Microsoft Corporation",
        doc_type=DocumentType.SEC_10K,
        fiscal_year=2024,
        fiscal_period="FY",
        title="Microsoft 2024 Annual Report",
        s3_raw_uri="s3://financial-filings/msam/msft-2024-10k.htm",
        file_size_bytes=24_500_000,
        chunk_count=210,
        content_hash="abc123hash456789",
        status=IngestionStatus.INDEXED,
    )
    async_db_session.add(doc)
    await async_db_session.commit()

    stmt = select(FinancialDocument).where(FinancialDocument.ticker == "MSFT")
    result = await async_db_session.execute(stmt)
    retrieved_doc = result.scalar_one_or_none()

    assert retrieved_doc is not None
    assert retrieved_doc.chunk_count == 210
    assert retrieved_doc.doc_type == DocumentType.SEC_10K


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hitl_task_and_security_audit_event(async_db_session: AsyncSession, sample_tenant: Tenant):
    """Verify Human-in-the-Loop review task and immutable security audit event."""
    task = HITLReviewTask(
        tenant_id=sample_tenant.id,
        thread_id="thread-langgraph-8899",
        trigger_reason=HITLTriggerReason.HIGH_RISK_THRESHOLD,
        risk_score=8.15,
        original_query="Run portfolio VaR with 200bps rate hike",
        generated_report_draft="Estimated 1-day 99% VaR is 8.15%, breaching 5.0% threshold.",
        status=HITLReviewStatus.PENDING,
    )
    async_db_session.add(task)
    await async_db_session.commit()

    audit_entry = SecurityAuditEvent(
        tenant_id=sample_tenant.id,
        user_id="user-sys-admin",
        action="HITL_TASK_TRIGGERED",
        resource_type="HITL_TASK",
        resource_id=task.id,
        status=AuditActionStatus.SUCCESS,
        request_id="req-audit-9999",
        details="Automated LangGraph interrupt tripped due to VaR breach.",
    )
    async_db_session.add(audit_entry)
    await async_db_session.commit()

    stmt = select(HITLReviewTask).where(HITLReviewTask.thread_id == "thread-langgraph-8899")
    result = await async_db_session.execute(stmt)
    retrieved_task = result.scalar_one_or_none()

    assert retrieved_task is not None
    assert retrieved_task.risk_score == 8.15
    assert retrieved_task.status == HITLReviewStatus.PENDING

    audit_stmt = select(SecurityAuditEvent).where(SecurityAuditEvent.resource_id == task.id)
    audit_res = await async_db_session.execute(audit_stmt)
    retrieved_audit = audit_res.scalar_one_or_none()
    assert retrieved_audit is not None
    assert retrieved_audit.status == AuditActionStatus.SUCCESS

