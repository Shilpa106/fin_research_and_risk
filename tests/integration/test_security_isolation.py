import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tool_guard import AgentToolSecurityGuard
from src.application.services.auth_service import AuthService
from src.application.services.conversation_service import ConversationService
from src.application.services.document_service import DocumentService
from src.application.services.portfolio_service import PortfolioService
from src.domain.entities import (
    AuditActionStatus,
    Role,
    RoleType,
    SecurityAuditEvent,
    Tenant,
    TenantMembership,
    TenantTier,
    User,
)
from src.domain.exceptions import (
    AuthorizationException,
    TenantIsolationViolationException,
)
from src.rag.tenant_filter import RetrievalTenantFilterGuard
from src.security.auth import create_access_token, hash_password
from src.security.context import RequestSecurityContext
from src.security.rbac import PERMISSIONS_MAP


async def create_test_tenant(session: AsyncSession, name: str, slug: str) -> Tenant:
    tenant = Tenant(
        name=name,
        slug=slug,
        tier=TenantTier.ENTERPRISE,
        max_rate_limit_rps=2000,
        hitl_threshold_var=0.05,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


async def create_test_user_with_role(
    session: AsyncSession,
    tenant: Tenant,
    email: str,
    role_type: RoleType,
    password: str = "P@ssword12345!",
) -> tuple[User, str]:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=f"User {email}",
    )
    session.add(user)
    await session.flush()

    # Get or create Role
    stmt = select(Role).where(Role.name == role_type)
    res = await session.execute(stmt)
    role = res.scalar_one_or_none()
    if not role:
        role = Role(name=role_type, description=f"Role {role_type.value}")
        session.add(role)
        await session.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        is_active=True,
    )
    membership.roles.append(role)
    session.add(membership)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        email=user.email,
        roles=[role_type],
    )
    return user, token


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_tenant_document_access_denied(
    test_client: AsyncClient, async_db_session: AsyncSession
):
    """
    CRITICAL TEST: Tenant A user stores a document.
    Tenant B user attempts to retrieve Tenant A's document.
    Must be blocked at both API layer (HTTP 403) and Service/Repository layer.
    """
    tenant_a = await create_test_tenant(async_db_session, "Goldman Sachs", "gs-bank")
    tenant_b = await create_test_tenant(async_db_session, "BlackRock", "blk-asset")

    _, token_a = await create_test_user_with_role(
        async_db_session, tenant_a, "analyst@gs.com", RoleType.ANALYST
    )
    user_b, token_b = await create_test_user_with_role(
        async_db_session, tenant_b, "analyst@blackrock.com", RoleType.ANALYST
    )

    # 1. Tenant A uploads confidential document
    post_resp = await test_client.post(
        "/api/v1/research/documents",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "title": "Goldman M&A Confidential Deck",
            "ticker": "GS",
            "doc_type": "10-K",
            "content": "Confidential advisory strategies.",
            "content_hash": "gs-secret-hash-001",
        },
    )
    assert post_resp.status_code == 200
    doc_id = post_resp.json()["id"]

    # 2. Tenant B attempts to access Tenant A's document via API
    get_resp = await test_client.get(
        f"/api/v1/research/documents/{doc_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_resp.status_code == 403
    error_data = get_resp.json()
    assert error_data["error"] in ["TENANT_ISOLATION_VIOLATION", "PERMISSION_DENIED"]

    # 3. Direct Service Layer validation: Tenant B context cannot fetch Tenant A doc
    b_context = RequestSecurityContext(
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        roles=[RoleType.ANALYST],
        permissions=PERMISSIONS_MAP[RoleType.ANALYST],
        request_id="req-direct-attack-doc",
    )
    doc_service = DocumentService(async_db_session)
    with pytest.raises(TenantIsolationViolationException):
        await doc_service.get_document(b_context, doc_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_tenant_conversation_access_denied(
    test_client: AsyncClient, async_db_session: AsyncSession
):
    """
    CRITICAL TEST: Tenant A user creates a copilot conversation session.
    Tenant B user attempts to retrieve that conversation thread.
    Must be blocked at API layer (HTTP 403) and Service/Repository layer.
    """
    tenant_a = await create_test_tenant(async_db_session, "JPMorgan Chase", "jpm-bank")
    tenant_b = await create_test_tenant(async_db_session, "Citigroup", "citi-bank")

    _, token_a = await create_test_user_with_role(
        async_db_session, tenant_a, "advisor@jpm.com", RoleType.ADVISOR
    )
    user_b, token_b = await create_test_user_with_role(
        async_db_session, tenant_b, "advisor@citi.com", RoleType.ADVISOR
    )

    # 1. Tenant A creates conversation session
    create_resp = await test_client.post(
        "/api/v1/copilot/conversations",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Private Client Wealth Allocation 2026"},
    )
    assert create_resp.status_code == 200
    thread_id = create_resp.json()["id"]

    # 2. Tenant B attempts to read Tenant A's conversation session
    read_resp = await test_client.get(
        f"/api/v1/copilot/conversations/{thread_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert read_resp.status_code == 403
    assert read_resp.json()["error"] in ["TENANT_ISOLATION_VIOLATION", "PERMISSION_DENIED"]

    # 3. Direct Service Layer test
    b_context = RequestSecurityContext(
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        roles=[RoleType.ADVISOR],
        permissions=PERMISSIONS_MAP[RoleType.ADVISOR],
        request_id="req-direct-attack-conv",
    )
    conv_service = ConversationService(async_db_session)
    with pytest.raises(TenantIsolationViolationException):
        await conv_service.get_conversation(b_context, thread_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unauthorized_portfolio_access_denied(
    test_client: AsyncClient, async_db_session: AsyncSession
):
    """
    CRITICAL TEST:
    1. Cross-tenant portfolio reading attempt must return HTTP 403.
    2. READ_ONLY_USER attempting to create/modify a portfolio must return HTTP 403.
    """
    tenant_a = await create_test_tenant(async_db_session, "Bridgewater", "bwater")
    tenant_b = await create_test_tenant(async_db_session, "Renaissance Tech", "rentec")

    _, rm_token_a = await create_test_user_with_role(
        async_db_session, tenant_a, "risk@bwater.com", RoleType.RISK_MANAGER
    )
    _, ro_token_a = await create_test_user_with_role(
        async_db_session, tenant_a, "intern@bwater.com", RoleType.READ_ONLY_USER
    )
    user_b, token_b = await create_test_user_with_role(
        async_db_session, tenant_b, "quant@rentec.com", RoleType.ANALYST
    )

    # 1. Tenant A creates portfolio
    port_resp = await test_client.post(
        "/api/v1/risk/portfolios",
        headers={"Authorization": f"Bearer {rm_token_a}"},
        json={
            "name": "Pure Alpha Macro Flagship",
            "benchmark": "SPY",
            "total_value": 500000000.0,
            "positions_json": '[{"ticker":"SPY","weight":0.4}]',
            "description": "Systematic global macro fund",
        },
    )
    assert port_resp.status_code == 200
    portfolio_id = port_resp.json()["id"]

    # 2. Cross-tenant read attempt: Tenant B quant attempts to read Portfolio A
    cross_resp = await test_client.get(
        f"/api/v1/risk/portfolios/{portfolio_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_resp.status_code == 403
    assert cross_resp.json()["error"] in ["TENANT_ISOLATION_VIOLATION", "PERMISSION_DENIED"]

    # 3. Direct Service Layer test for cross-tenant portfolio access
    b_context = RequestSecurityContext(
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        roles=[RoleType.ANALYST],
        permissions=PERMISSIONS_MAP[RoleType.ANALYST],
        request_id="req-cross-port",
    )
    port_service = PortfolioService(async_db_session)
    with pytest.raises(TenantIsolationViolationException):
        await port_service.get_portfolio(b_context, portfolio_id)

    # 4. Role authorization denial: READ_ONLY_USER attempts to create portfolio
    ro_create_resp = await test_client.post(
        "/api/v1/risk/portfolios",
        headers={"Authorization": f"Bearer {ro_token_a}"},
        json={
            "name": "Unauthorized Rogue Portfolio",
            "benchmark": "QQQ",
            "total_value": 1000000.0,
        },
    )
    assert ro_create_resp.status_code == 403
    assert ro_create_resp.json()["error"] == "PERMISSION_DENIED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unauthorized_tool_invocation_denied(async_db_session: AsyncSession):
    """
    CRITICAL TEST: Agent/Tool execution layer security guard.
    1. Cross-tenant tool execution is rejected and audited.
    2. Role/Permission violation is rejected and audited.
    """
    tenant_a = await create_test_tenant(async_db_session, "Two Sigma", "twosigma")
    tenant_b = await create_test_tenant(async_db_session, "DE Shaw", "deshaw")

    user_a, _ = await create_test_user_with_role(
        async_db_session, tenant_a, "researcher@twosigma.com", RoleType.ANALYST
    )

    analyst_context = RequestSecurityContext(
        tenant_id=tenant_a.id,
        user_id=user_a.id,
        roles=[RoleType.ANALYST],
        permissions=PERMISSIONS_MAP[RoleType.ANALYST],
        request_id="req-tool-test-1",
    )

    # Test 1: Cross-tenant tool call attempt
    with pytest.raises(AuthorizationException) as exc_info:
        await AgentToolSecurityGuard.authorize_tool_call(
            tool_name="market_data_quote",
            target_tenant_id=tenant_b.id,  # Target is different tenant!
            context=analyst_context,
            session=async_db_session,
        )
    assert "Tenant" in str(exc_info.value)

    # Verify audit event recorded for cross-tenant tool call
    audit_stmt = select(SecurityAuditEvent).where(
        SecurityAuditEvent.action == "UNAUTHORIZED_CROSS_TENANT_TOOL_CALL"
    )
    audit_res = await async_db_session.execute(audit_stmt)
    audit_event = audit_res.scalar_one_or_none()
    assert audit_event is not None
    assert audit_event.status == AuditActionStatus.DENIED
    assert audit_event.tenant_id == tenant_a.id

    # Test 2: Analyst attempting to execute admin tool (modify_risk_limits)
    with pytest.raises(AuthorizationException) as exc_info2:
        await AgentToolSecurityGuard.authorize_tool_call(
            tool_name="modify_risk_limits",  # Requires tools:execute:admin
            target_tenant_id=tenant_a.id,
            context=analyst_context,
            session=async_db_session,
        )
    assert "tools:execute:admin" in str(exc_info2.value)

    # Verify audit event recorded for unauthorized tool invocation
    audit_stmt2 = select(SecurityAuditEvent).where(
        SecurityAuditEvent.action == "UNAUTHORIZED_TOOL_INVOCATION"
    )
    audit_res2 = await async_db_session.execute(audit_stmt2)
    audit_event2 = audit_res2.scalar_one_or_none()
    assert audit_event2 is not None
    assert audit_event2.status == AuditActionStatus.DENIED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_role_escalation_attempt_denied(
    test_client: AsyncClient, async_db_session: AsyncSession
):
    """
    CRITICAL TEST: A non-admin user (ANALYST) attempts to escalate privileges
    by assigning the ADMIN role to themselves or another user.
    Must be blocked at API layer and Service layer with security audit event recorded.
    """
    tenant = await create_test_tenant(async_db_session, "Vanguard", "vanguard")

    target_user, _ = await create_test_user_with_role(
        async_db_session, tenant, "junior@vanguard.com", RoleType.READ_ONLY_USER
    )
    attacker_user, attacker_token = await create_test_user_with_role(
        async_db_session, tenant, "attacker@vanguard.com", RoleType.ANALYST
    )

    # 1. Attacker attempts to promote junior_user to ADMIN via API
    resp = await test_client.post(
        "/api/v1/auth/roles/assign",
        headers={"Authorization": f"Bearer {attacker_token}"},
        json={
            "target_user_id": target_user.id,
            "new_role": "ADMIN",
        },
    )
    assert resp.status_code == 403

    # 2. Attacker attempts direct Service Layer invocation with non-admin context
    attacker_context = RequestSecurityContext(
        tenant_id=tenant.id,
        user_id=attacker_user.id,
        roles=[RoleType.ANALYST],
        permissions=PERMISSIONS_MAP[RoleType.ANALYST],
        request_id="req-escalation-attack",
    )
    auth_service = AuthService(async_db_session)
    with pytest.raises(AuthorizationException):
        await auth_service.assign_user_role(
            context=attacker_context,
            target_user_id=target_user.id,
            new_role=RoleType.ADMIN,
        )

    # 3. Verify security audit events recorded for escalation attempts (both API and service layers)
    audit_stmt = select(SecurityAuditEvent).where(
        SecurityAuditEvent.action.in_(["ROLE_ESCALATION_ATTEMPT", "ROLE_UNAUTHORIZED"])
    )
    audit_res = await async_db_session.execute(audit_stmt)
    audit_events = list(audit_res.scalars().all())
    assert len(audit_events) >= 1
    assert all(e.status == AuditActionStatus.DENIED for e in audit_events)
    assert any(e.user_id == attacker_user.id for e in audit_events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_token_rotation_and_replay_detection(
    test_client: AsyncClient, async_db_session: AsyncSession
):
    """
    CRITICAL TEST: Refresh token strategy & replay attack detection.
    1. User logs in via /auth/token and obtains access & refresh token.
    2. Legitimate refresh rotates token and invalidates prior token.
    3. Attacker attempts to replay old refresh token.
    4. Server detects replay, revokes all tokens in family, and records audit event.
    """
    tenant = await create_test_tenant(async_db_session, "Millennium Management", "mlpm")
    pwd = "Secr3tPassword2026!"
    await create_test_user_with_role(
        async_db_session, tenant, "portfolio_manager@mlpm.com", RoleType.ADVISOR, password=pwd
    )

    # 1. Login via /api/v1/auth/token
    login_resp = await test_client.post(
        "/api/v1/auth/token",
        json={
            "email": "portfolio_manager@mlpm.com",
            "password": pwd,
            "tenant_slug": "mlpm",
        },
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    first_refresh = tokens["refresh_token"]
    assert first_refresh is not None

    # 2. Legitimate refresh: exchange first_refresh for second_refresh
    refresh_resp1 = await test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert refresh_resp1.status_code == 200
    tokens2 = refresh_resp1.json()
    second_refresh = tokens2["refresh_token"]
    assert second_refresh != first_refresh

    # 3. Replay attack: Attacker attempts to reuse first_refresh (which was already revoked)
    replay_resp = await test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert replay_resp.status_code == 401
    assert "reuse detected" in replay_resp.json()["message"].lower()

    # 4. Verify REFRESH_TOKEN_REPLAY_DETECTED audit event recorded
    audit_stmt = select(SecurityAuditEvent).where(
        SecurityAuditEvent.action == "REFRESH_TOKEN_REPLAY_DETECTED"
    )
    audit_res = await async_db_session.execute(audit_stmt)
    audit_event = audit_res.scalar_one_or_none()
    assert audit_event is not None
    assert audit_event.status == AuditActionStatus.DENIED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retrieval_cross_tenant_filter_injection_enforced(async_db_session: AsyncSession):
    """
    CRITICAL TEST: Retrieval layer tenant filtering.
    1. Tenant A search query must inject tenant_id='tenant-A'.
    2. Attempt to query Tenant B with Tenant A context raises TenantIsolationViolationException.
    """
    tenant_a = await create_test_tenant(async_db_session, "Point72", "p72")
    tenant_b = await create_test_tenant(async_db_session, "Citadel", "citadel")

    context_a = RequestSecurityContext(
        tenant_id=tenant_a.id,
        user_id="user-p72-1",
        roles=[RoleType.ANALYST],
        permissions=PERMISSIONS_MAP[RoleType.ANALYST],
        request_id="req-rag-filter-1",
    )

    # 1. Normal query: tenant_id filter is injected correctly
    base_query = {"query": {"match": {"content": "earnings per share"}}}
    filtered_query = RetrievalTenantFilterGuard.inject_mandatory_tenant_filter(
        query_body=base_query,
        context=context_a,
        target_tenant_id=tenant_a.id,
    )
    filter_clauses = filtered_query["query"]["bool"]["filter"]
    assert any(clause.get("term", {}).get("tenant_id") == tenant_a.id for clause in filter_clauses)

    # 2. Cross-tenant search attempt: Context A targeting Tenant B
    with pytest.raises(TenantIsolationViolationException):
        RetrievalTenantFilterGuard.inject_mandatory_tenant_filter(
            query_body={"query": {"match_all": {}}},
            context=context_a,
            target_tenant_id=tenant_b.id,
        )
