"""
Database Seeding Script for Local Development & Swagger Testing.
Populates SQLite `./financial_copilot_dev.db` with demo tenants, users, roles, and records.
"""

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import (
    Base,
    Document,
    DocumentType,
    HITLReviewStatus,
    HITLTask,
    HITLTriggerReason,
    IngestionStatus,
    Permission,
    Portfolio,
    Role,
    RoleType,
    Tenant,
    TenantMembership,
    TenantTier,
    User,
)
from src.infrastructure.database import async_session_factory, init_db_schema
from src.security.auth import hash_password


async def seed():
    print("Initializing database schema...")
    await init_db_schema()

    async with async_session_factory() as session:
        # 1. Seed Roles & Permissions
        role_map = {}
        for role_type in RoleType:
            stmt = select(Role).where(Role.name == role_type)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                r = Role(name=role_type, description=f"Default role for {role_type.value}")
                session.add(r)
                role_map[role_type] = r
            else:
                role_map[role_type] = existing

        await session.flush()

        # 2. Seed Tenant
        tenant_stmt = select(Tenant).where(Tenant.slug == "apex-capital")
        tenant = (await session.execute(tenant_stmt)).scalar_one_or_none()
        if not tenant:
            tenant = Tenant(
                name="Apex Capital Management",
                slug="apex-capital",
                tier=TenantTier.ENTERPRISE,
                max_rate_limit_rps=5000,
                hitl_threshold_var=0.05,
                enable_semantic_cache=True,
                is_active=True,
            )
            session.add(tenant)
            await session.flush()
            print(f"Created Tenant: {tenant.name} (Slug: {tenant.slug}, ID: {tenant.id})")
        else:
            print(f"Using existing Tenant: {tenant.name} (Slug: {tenant.slug}, ID: {tenant.id})")

        # 3. Seed Users
        users_to_seed = [
            ("analyst@apexcapital.com", "Password123!", "Senior Quant Analyst", RoleType.ANALYST),
            ("admin@apexcapital.com", "Password123!", "Enterprise Admin", RoleType.ADMIN),
            ("risk_officer@apexcapital.com", "Password123!", "Chief Risk Officer", RoleType.RISK_MANAGER),
        ]

        for email, pwd, name, role_enum in users_to_seed:
            u_stmt = select(User).where(User.email == email)
            user = (await session.execute(u_stmt)).scalar_one_or_none()
            if not user:
                user = User(
                    email=email,
                    hashed_password=hash_password(pwd),
                    full_name=name,
                    is_active=True,
                )
                session.add(user)
                await session.flush()

                # Add Tenant Membership
                mem = TenantMembership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    is_active=True,
                )
                mem.roles.append(role_map[role_enum])
                session.add(mem)
                print(f"Created User: {email} with role {role_enum.value}")
            else:
                print(f"User already exists: {email}")

        # 4. Seed Demo Portfolio
        p_stmt = select(Portfolio).where(Portfolio.tenant_id == tenant.id)
        portfolio = (await session.execute(p_stmt)).scalars().first()
        if not portfolio:
            portfolio = Portfolio(
                tenant_id=tenant.id,
                name="Global Tech & Credit Growth Portfolio",
                description="Institutional long/short equity and debt stress-test portfolio",
                base_currency="USD",
                total_value=250000000.0,
                assets=[
                    {"symbol": "AAPL", "weight": 0.35, "asset_class": "equity", "exposure": 87500000.0},
                    {"symbol": "MSFT", "weight": 0.30, "asset_class": "equity", "exposure": 75000000.0},
                    {"symbol": "NVDA", "weight": 0.20, "asset_class": "equity", "exposure": 50000000.0},
                    {"symbol": "US10Y", "weight": 0.15, "asset_class": "fixed_income", "exposure": 37500000.0},
                ],
            )
            session.add(portfolio)
            await session.flush()
            print(f"Created Portfolio: {portfolio.name} (ID: {portfolio.id})")

        # 5. Seed Demo Document
        doc_stmt = select(Document).where(Document.tenant_id == tenant.id)
        doc = (await session.execute(doc_stmt)).scalars().first()
        if not doc:
            doc = Document(
                tenant_id=tenant.id,
                title="Apple Inc. FY2023 Form 10-K Annual Report",
                ticker="AAPL",
                cik="0000320193",
                filing_type="10-K",
                document_type=DocumentType.SEC_10K,
                filing_date=datetime(2023, 11, 3),
                fiscal_period="FY2023",
                fiscal_year=2023,
                s3_bucket="copilot-financial-docs-dev",
                s3_key="filings/AAPL/2023/10K.pdf",
                source_url="https://www.sec.gov/edgar/data/320193/000032019323000106/aapl-20230930.htm",
                file_size_bytes=1420580,
                content_hash="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                chunk_count=240,
                ingestion_status=IngestionStatus.COMPLETED,
            )
            session.add(doc)
            await session.flush()
            print(f"Created Document: {doc.title} (ID: {doc.id})")

        # 6. Seed Demo HITL Task
        task_stmt = select(HITLTask).where(HITLTask.tenant_id == tenant.id)
        task = (await session.execute(task_stmt)).scalars().first()
        if not task:
            task = HITLTask(
                tenant_id=tenant.id,
                trigger_reason=HITLTriggerReason.HIGH_RISK_THRESHOLD,
                status=HITLReviewStatus.PENDING,
                threshold_exceeded="95% VaR: 6.8% (Threshold: 5.0%)",
                workflow_name="macro_interest_rate_stress_test",
                tool_call_payload={
                    "portfolio_id": portfolio.id,
                    "shock_scenario": "150bps_yield_curve_steepener",
                    "estimated_loss_usd": 17000000.0,
                    "calculated_var_95": 0.068,
                },
                agent_context={"agent": "Quantitative Risk Assessor", "recommendation": "Require human signoff prior to trade rebalancing"},
            )
            session.add(task)
            await session.flush()
            print(f"Created HITL Task: {task.id}")

        await session.commit()
        print("\nSUCCESS: Database successfully seeded with demo enterprise data!")


if __name__ == "__main__":
    asyncio.run(seed())
