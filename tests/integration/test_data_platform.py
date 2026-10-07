import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import (
    Document,
    DocumentType,
    Tenant,
    TenantTier,
)
from src.domain.exceptions import (
    EntityNotFoundException,
    OptimisticConcurrencyException,
    TenantIsolationViolationException,
)
from src.infrastructure.database import execute_with_retry
from src.infrastructure.repositories.agent_run_repository import AgentRunRepository
from src.infrastructure.repositories.conversation_repository import ConversationRepository
from src.infrastructure.repositories.document_repository import DocumentRepository
from src.infrastructure.repositories.evaluation_repository import EvaluationRepository
from src.infrastructure.repositories.pagination import PageParams
from src.infrastructure.repositories.portfolio_repository import PortfolioRepository
from src.infrastructure.repositories.user_repository import UserRepository


async def create_helper_tenant(session: AsyncSession, name: str, slug: str) -> Tenant:
    tenant = Tenant(
        name=name,
        slug=slug,
        tier=TenantTier.ENTERPRISE,
        max_rate_limit_rps=2000,
        hitl_threshold_var=0.05,
        is_deleted=False,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


# ==============================================================================
# 1. CRUD Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_crud_with_versions_and_metadata(async_db_session: AsyncSession):
    """Verify Document CRUD lifecycle with DocumentVersion and DocumentMetadata."""
    tenant = await create_helper_tenant(async_db_session, "Fidelity Investments", "fidelity")
    repo = DocumentRepository(async_db_session)

    # 1. Create document
    doc = await repo.create(
        tenant_id=tenant.id,
        title="Fidelity 2026 Macro Strategy",
        ticker="SPY",
        company_name="State Street Global Advisors",
        doc_type=DocumentType.EQUITY_RESEARCH,
        content="Global equity overweight recommendations.",
        content_hash="hash-macro-2026-v1",
        s3_raw_uri="s3://research/fidelity/macro-2026-v1.pdf",
        file_size_bytes=1048576,
    )
    assert doc.id is not None
    assert doc.version == 1
    assert doc.is_deleted is False

    # 2. Add second version
    v2 = await repo.add_version(
        tenant_id=tenant.id,
        document_id=doc.id,
        s3_uri="s3://research/fidelity/macro-2026-v2.pdf",
        content_hash="hash-macro-2026-v2",
        file_size_bytes=1055000,
        chunk_count=42,
        change_summary="Revised sector weights",
    )
    assert v2.version_number == 2
    assert doc.version == 2

    # 3. Add structured metadata
    meta = await repo.add_metadata(
        tenant_id=tenant.id,
        document_id=doc.id,
        meta_key="macro_cycle",
        meta_value="late_expansion",
        data_type="string",
    )
    assert meta.id is not None

    # 4. Read back with relations
    fetched = await repo.get_by_id(tenant_id=tenant.id, document_id=doc.id, load_relations=True)
    assert len(fetched.versions) == 2
    assert len(fetched.metadata_items) == 1
    assert fetched.metadata_items[0].meta_key == "macro_cycle"

    # 5. Soft delete
    await repo.soft_delete(tenant_id=tenant.id, document_id=doc.id)
    with pytest.raises(EntityNotFoundException):
        await repo.get_by_id(tenant_id=tenant.id, document_id=doc.id, include_deleted=False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_portfolio_crud_with_holdings_and_risk(async_db_session: AsyncSession):
    """Verify Portfolio CRUD lifecycle with Holding and RiskAssessment."""
    tenant = await create_helper_tenant(async_db_session, "AQR Capital", "aqr")
    repo = PortfolioRepository(async_db_session)

    # 1. Create portfolio
    port = await repo.create(
        tenant_id=tenant.id,
        name="AQR Global Systematic Alpha",
        benchmark="MSCI_WORLD",
        total_value=250000000.0,
        description="Multi-factor market-neutral portfolio",
    )
    assert port.id is not None
    assert port.version == 1

    # 2. Add Holdings
    h1 = await repo.add_holding(
        tenant_id=tenant.id,
        portfolio_id=port.id,
        ticker="NVDA",
        shares=10000.0,
        market_price=125.0,
        market_value=1250000.0,
        weight=0.005,
    )
    assert h1.id is not None

    # 3. Add Risk Assessment
    risk = await repo.add_risk_assessment(
        tenant_id=tenant.id,
        portfolio_id=port.id,
        metric_value=5825000.0,
        assessment_type="VAR",
        confidence_level=0.99,
        horizon_days=20,
        rating="LOW",
        requires_hitl=False,
    )
    assert risk.id is not None

    # 4. Read back
    fetched = await repo.get_by_id(tenant_id=tenant.id, portfolio_id=port.id, load_relations=True)
    assert len(fetched.holdings) == 1
    assert fetched.holdings[0].ticker == "NVDA"
    assert len(fetched.risk_assessments) == 1
    assert fetched.risk_assessments[0].metric_value == 5825000.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conversation_crud_with_messages(async_db_session: AsyncSession):
    """Verify Conversation CRUD lifecycle with chronological Message ordering."""
    tenant = await create_helper_tenant(async_db_session, "D.E. Shaw & Co", "deshaw-quant")
    user_repo = UserRepository(async_db_session)
    user = await user_repo.create("quant@deshaw.com", "HashedPassw0rd!", "Quant Officer")

    repo = ConversationRepository(async_db_session)

    # 1. Create conversation
    conv = await repo.create(tenant_id=tenant.id, user_id=user.id, title="Commodities Arbitrage Inquiry")
    assert conv.id is not None

    # 2. Add messages
    m1 = await repo.add_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        role="user",
        content="What was the crude oil contango impact in Q3?",
        token_count=12,
    )
    m2 = await repo.add_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        role="assistant",
        content="Crude forward curves showed slight backwardation in front months.",
        token_count=18,
        latency_ms=145.2,
    )
    assert m1.id is not None
    assert m2.id is not None

    # 3. List messages
    messages = await repo.list_messages(tenant_id=tenant.id, conversation_id=conv.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_run_and_tool_execution_crud(async_db_session: AsyncSession):
    """Verify AgentRun lifecycle and ToolExecution tracking."""
    tenant = await create_helper_tenant(async_db_session, "Balyasny Asset Management", "bam")
    repo = AgentRunRepository(async_db_session)

    # 1. Create agent run
    run = await repo.create_agent_run(
        tenant_id=tenant.id,
        agent_name="RiskAgent",
        input_prompt="Compute 99% 10-day VaR on Tech sector basket",
    )
    assert run.id is not None
    assert run.status == "RUNNING"

    # 2. Record tool executions
    tool1 = await repo.record_tool_execution(
        tenant_id=tenant.id,
        agent_run_id=run.id,
        tool_name="market_data_quote",
        input_parameters_json='{"tickers": ["AAPL", "MSFT"]}',
        output_result_json='{"prices": [180.5, 420.1]}',
        status="SUCCESS",
        duration_ms=45.6,
    )
    assert tool1.id is not None

    # 3. Update agent run to completion
    updated = await repo.update_agent_run(
        tenant_id=tenant.id,
        run_id=run.id,
        status="COMPLETED",
        output_summary="Calculated 10-day VaR is $2.14M (1.8% of portfolio).",
        total_tokens=1420,
        cost_usd=0.0284,
        latency_ms=420.0,
    )
    assert updated.status == "COMPLETED"
    assert len(updated.tool_executions) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evaluation_run_crud(async_db_session: AsyncSession):
    """Verify EvaluationRun benchmark persistence and retrieval."""
    tenant = await create_helper_tenant(async_db_session, "Schonfeld Strategic", "schonfeld")
    repo = EvaluationRepository(async_db_session)

    run = await repo.create_evaluation_run(
        tenant_id=tenant.id,
        dataset_name="sec_10k_risk_factors_v2",
        model_id="anthropic.claude-3-5-sonnet-20241022",
        faithfulness_score=0.985,
        answer_relevance_score=0.972,
        hallucination_score=0.015,
        total_eval_samples=250,
        status="COMPLETED",
    )
    assert run.id is not None
    assert run.faithfulness_score == 0.985

    fetched = await repo.get_by_id(tenant_id=tenant.id, eval_id=run.id)
    assert fetched.model_id == "anthropic.claude-3-5-sonnet-20241022"


# ==============================================================================
# 2. Strict Tenant Isolation Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_tenant_isolation(async_db_session: AsyncSession):
    """Verify that every repository strictly raises TenantIsolationViolationException on cross-tenant access."""
    tenant_a = await create_helper_tenant(async_db_session, "AllianceBernstein", "ab-bank")
    tenant_b = await create_helper_tenant(async_db_session, "Invesco", "invesco")

    doc_repo = DocumentRepository(async_db_session)
    port_repo = PortfolioRepository(async_db_session)
    conv_repo = ConversationRepository(async_db_session)

    # 1. Tenant A creates resources
    doc_a = await doc_repo.create(
        tenant_id=tenant_a.id,
        title="AllianceBernstein Credit Memo",
        ticker="IBM",
        doc_type=DocumentType.CREDIT_MEMO,
    )
    port_a = await port_repo.create(
        tenant_id=tenant_a.id,
        name="AB High Yield Strategy",
        total_value=1000000.0,
    )
    conv_a = await conv_repo.create(
        tenant_id=tenant_a.id,
        user_id="user-temp-1",
        title="Fixed Income Analysis",
    )

    # 2. Tenant B attempts to fetch Tenant A resources -> MUST FAIL
    with pytest.raises(TenantIsolationViolationException):
        await doc_repo.get_by_id(tenant_id=tenant_b.id, document_id=doc_a.id)

    with pytest.raises(TenantIsolationViolationException):
        await port_repo.get_by_id(tenant_id=tenant_b.id, portfolio_id=port_a.id)

    with pytest.raises(TenantIsolationViolationException):
        await conv_repo.get_by_id(tenant_id=tenant_b.id, thread_id=conv_a.id)


# ==============================================================================
# 3. Pagination Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_pagination_flow(async_db_session: AsyncSession):
    """Verify offset-based pagination calculation and envelope metadata."""
    tenant = await create_helper_tenant(async_db_session, "Lazard Asset Management", "lazard")
    doc_repo = DocumentRepository(async_db_session)

    # Seed 12 documents for Tenant
    for i in range(12):
        await doc_repo.create(
            tenant_id=tenant.id,
            title=f"Lazard Research Note #{i+1:02d}",
            ticker="AAPL",
            doc_type=DocumentType.EQUITY_RESEARCH,
            content_hash=f"hash-paged-{i}",
        )

    # Page 1 (size 5) -> Items 0..4
    p1 = await doc_repo.list_paginated(
        tenant_id=tenant.id,
        page_params=PageParams(page=1, page_size=5),
    )
    assert len(p1.items) == 5
    assert p1.total_items == 12
    assert p1.total_pages == 3
    assert p1.has_next is True
    assert p1.has_prev is False

    # Page 2 (size 5) -> Items 5..9
    p2 = await doc_repo.list_paginated(
        tenant_id=tenant.id,
        page_params=PageParams(page=2, page_size=5),
    )
    assert len(p2.items) == 5
    assert p2.page == 2
    assert p2.has_next is True
    assert p2.has_prev is True

    # Page 3 (size 5) -> Items 10..11
    p3 = await doc_repo.list_paginated(
        tenant_id=tenant.id,
        page_params=PageParams(page=3, page_size=5),
    )
    assert len(p3.items) == 2
    assert p3.page == 3
    assert p3.has_next is False
    assert p3.has_prev is True


# ==============================================================================
# 4. Concurrent Updates (Optimistic Concurrency Control) Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_portfolio_optimistic_concurrency_conflict(async_db_session: AsyncSession):
    """
    CRITICAL TEST: Simulates two concurrent portfolio rebalances.
    Second update with stale expected_version must raise OptimisticConcurrencyException.
    """
    tenant = await create_helper_tenant(async_db_session, "Franklin Templeton", "franklin")
    repo = PortfolioRepository(async_db_session)

    # 1. Create portfolio (version = 1)
    port = await repo.create(
        tenant_id=tenant.id,
        name="Franklin Global Growth",
        total_value=100000000.0,
    )
    assert port.version == 1

    # 2. Transaction A reads version 1 and updates portfolio -> succeeds, version becomes 2
    updated_a = await repo.update_with_optimistic_lock(
        tenant_id=tenant.id,
        portfolio_id=port.id,
        expected_version=1,
        total_value=105000000.0,
        description="Rebalance A executed",
    )
    assert updated_a.version == 2
    assert updated_a.total_value == 105000000.0

    # 3. Transaction B (concurrent worker) attempts to update using stale version 1 -> MUST FAIL
    with pytest.raises(OptimisticConcurrencyException) as exc_info:
        await repo.update_with_optimistic_lock(
            tenant_id=tenant.id,
            portfolio_id=port.id,
            expected_version=1,  # Stale version!
            total_value=110000000.0,
            description="Rebalance B executed concurrently",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "OPTIMISTIC_CONCURRENCY_CONFLICT"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_optimistic_concurrency_conflict(async_db_session: AsyncSession):
    """Verify document metadata optimistic concurrency version conflict."""
    tenant = await create_helper_tenant(async_db_session, "T. Rowe Price", "trowe")
    repo = DocumentRepository(async_db_session)

    doc = await repo.create(
        tenant_id=tenant.id,
        title="Initial Filing Review",
        ticker="GOOGL",
        doc_type=DocumentType.SEC_10Q,
    )
    assert doc.version == 1

    # Update 1 -> version becomes 2
    await repo.update_with_optimistic_lock(
        tenant_id=tenant.id,
        document_id=doc.id,
        expected_version=1,
        title="Updated Filing Review V2",
    )

    # Update 2 with stale version 1 -> raises OptimisticConcurrencyException
    with pytest.raises(OptimisticConcurrencyException):
        await repo.update_with_optimistic_lock(
            tenant_id=tenant.id,
            document_id=doc.id,
            expected_version=1,
            title="Conflicting Update",
        )


# ==============================================================================
# 5. Transaction Rollback Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_transaction_rollback_on_failure(async_db_session: AsyncSession):
    """
    CRITICAL TEST: Ensures that an unhandled exception rolls back the transaction,
    leaving no orphaned or partially written entities.
    """
    tenant = await create_helper_tenant(async_db_session, "Wellington Management", "wellington")
    unique_title = "Wellington Sovereign Debt Analysis 2026"

    # Attempt atomic multi-step operation that fails midway
    try:
        async with async_db_session.begin_nested():
            # Step 1: Add document
            doc = Document(
                tenant_id=tenant.id,
                title=unique_title,
                ticker="TLT",
                doc_type=DocumentType.CREDIT_MEMO,
                content_hash="hash-fail-rollback",
                version=1,
            )
            async_db_session.add(doc)
            await async_db_session.flush()

            # Step 2: Simulate failure (e.g. database error or validation error)
            raise RuntimeError("Midway atomic pipeline failure!")
    except RuntimeError:
        pass

    # Verify that the document was rolled back and is NOT present in the database
    stmt = select(Document).where(Document.title == unique_title)
    res = await async_db_session.execute(stmt)
    persisted_doc = res.scalar_one_or_none()
    assert persisted_doc is None, "Failed transaction was not properly rolled back!"


# ==============================================================================
# 6. Database Failure & Retry Resilience Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_failure_retry_success():
    """Verify that execute_with_retry successfully recovers from transient database errors."""
    attempts = 0

    async def transient_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionResetError(f"Simulated DB disconnect attempt {attempts}")
        return "SUCCESSFUL_DB_QUERY_RESULT"

    result = await execute_with_retry(
        transient_operation,
        max_retries=3,
        initial_delay=0.01,
        backoff_factor=1.5,
    )
    assert result == "SUCCESSFUL_DB_QUERY_RESULT"
    assert attempts == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_permanent_failure_exhausts_retries():
    """Verify that permanent database failures raise the exception after exhausting retries."""
    attempts = 0

    async def permanent_failure_operation():
        nonlocal attempts
        attempts += 1
        raise ConnectionRefusedError("Database instance completely unreachable")

    with pytest.raises(ConnectionRefusedError):
        await execute_with_retry(
            permanent_failure_operation,
            max_retries=3,
            initial_delay=0.01,
            backoff_factor=1.5,
        )

    assert attempts == 3
