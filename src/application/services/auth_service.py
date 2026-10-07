
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import AuditActionStatus, Role, RoleType, Tenant, TenantMembership, User
from ...domain.exceptions import AuthenticationException, AuthorizationException, EntityNotFoundException
from ...security.audit import record_security_audit_event
from ...security.auth import (
    create_access_token,
    create_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from ...security.context import RequestSecurityContext


class AuthService:
    """Enterprise authentication and session orchestration service."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def authenticate_user(
        self,
        email: str,
        password: str,
        tenant_slug: str,
        ip_address: str | None = None,
        request_id: str | None = None
    ) -> tuple[str, str, str, str, list[RoleType]]:
        """
        Authenticates user credentials against tenant boundary.
        Returns: (access_token, refresh_token, tenant_id, user_id, roles)
        """
        # 1. Resolve tenant
        t_stmt = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)  # noqa: E712
        t_res = await self.session.execute(t_stmt)
        tenant = t_res.scalar_one_or_none()
        if not tenant:
            raise AuthenticationException(f"Tenant '{tenant_slug}' does not exist or is inactive.")

        # 2. Resolve user
        u_stmt = select(User).where(User.email == email, User.is_active == True)  # noqa: E712
        u_res = await self.session.execute(u_stmt)
        user = u_res.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            await record_security_audit_event(
                session=self.session,
                tenant_id=tenant.id,
                action="USER_LOGIN_FAILED",
                status=AuditActionStatus.DENIED,
                resource_type="USER",
                user_id=user.id if user else None,
                ip_address=ip_address,
                request_id=request_id,
                details={"email": email, "tenant_slug": tenant_slug}
            )
            raise AuthenticationException("Invalid email or password.")

        # 3. Resolve active tenant membership with eager loaded roles
        from sqlalchemy.orm import selectinload
        m_stmt = (
            select(TenantMembership)
            .options(selectinload(TenantMembership.roles))
            .where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == user.id,
                TenantMembership.is_active == True  # noqa: E712
            )
        )
        m_res = await self.session.execute(m_stmt)
        membership = m_res.scalar_one_or_none()
        if not membership:
            await record_security_audit_event(
                session=self.session,
                tenant_id=tenant.id,
                action="TENANT_MEMBERSHIP_MISSING",
                status=AuditActionStatus.DENIED,
                resource_type="TENANT",
                user_id=user.id,
                ip_address=ip_address,
                request_id=request_id
            )
            raise AuthenticationException(f"User is not an active member of tenant '{tenant_slug}'.")

        roles = [r.name for r in membership.roles]
        if not roles:
            roles = [RoleType.READ_ONLY_USER]

        # 4. Generate access token & refresh token
        access_token = create_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            email=user.email,
            roles=roles
        )
        refresh_token = await create_refresh_token(
            session=self.session,
            user_id=user.id,
            tenant_id=tenant.id
        )

        await record_security_audit_event(
            session=self.session,
            tenant_id=tenant.id,
            action="USER_LOGIN_SUCCESS",
            status=AuditActionStatus.SUCCESS,
            resource_type="USER",
            user_id=user.id,
            ip_address=ip_address,
            request_id=request_id,
            details={"roles": [r.value for r in roles]}
        )

        return access_token, refresh_token, tenant.id, user.id, roles

    async def refresh_session(
        self,
        raw_refresh_token: str,
        ip_address: str | None = None,
        request_id: str | None = None
    ) -> tuple[str, str, str, list[RoleType]]:
        """Rotates refresh token and issues new access token."""
        return await rotate_refresh_token(
            session=self.session,
            raw_refresh_token=raw_refresh_token,
            request_id=request_id,
            ip_address=ip_address
        )

    async def assign_user_role(
        self,
        context: RequestSecurityContext,
        target_user_id: str,
        new_role: RoleType
    ) -> None:
        """
        Assigns or updates role for a user within tenant.
        CRITICAL CHECK: Role escalation defense. Only ADMIN can assign roles.
        """
        # Role Escalation Check
        if not context.is_admin():
            await record_security_audit_event(
                session=self.session,
                tenant_id=context.tenant_id,
                action="ROLE_ESCALATION_ATTEMPT",
                status=AuditActionStatus.DENIED,
                resource_type="USER_ROLE",
                resource_id=target_user_id,
                user_id=context.user_id,
                ip_address=context.client_ip,
                request_id=context.request_id,
                details={"attempted_role": new_role.value}
            )
            raise AuthorizationException(
                f"Role escalation violation: Caller with roles {[r.value for r in context.roles]} cannot assign role '{new_role.value}'."
            )

        # Retrieve membership
        stmt = select(TenantMembership).where(
            TenantMembership.tenant_id == context.tenant_id,
            TenantMembership.user_id == target_user_id
        )
        res = await self.session.execute(stmt)
        membership = res.scalar_one_or_none()
        if not membership:
            raise EntityNotFoundException("TenantMembership", target_user_id)

        # Retrieve role entity
        role_stmt = select(Role).where(Role.name == new_role)
        role_res = await self.session.execute(role_stmt)
        role_record = role_res.scalar_one_or_none()
        if not role_record:
            role_record = Role(name=new_role, description=f"System role {new_role.value}")
            self.session.add(role_record)
            await self.session.flush()

        membership.roles = [role_record]
        await self.session.commit()

        await record_security_audit_event(
            session=self.session,
            tenant_id=context.tenant_id,
            action="ROLE_ASSIGNMENT_UPDATED",
            status=AuditActionStatus.SUCCESS,
            resource_type="USER_ROLE",
            resource_id=target_user_id,
            user_id=context.user_id,
            ip_address=context.client_ip,
            request_id=context.request_id,
            details={"assigned_role": new_role.value}
        )
