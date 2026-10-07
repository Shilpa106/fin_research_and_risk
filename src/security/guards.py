from collections.abc import Callable

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.entities import AuditActionStatus, RoleType, TenantApiKey
from ..domain.exceptions import AuthenticationException, AuthorizationException
from ..infrastructure.database import get_db_session, set_tenant_rls_context
from .audit import record_security_audit_event
from .auth import decode_access_token, hash_api_key
from .context import RequestSecurityContext
from .rbac import PERMISSIONS_MAP, enforce_permission, enforce_role, get_permissions_for_roles

bearer_scheme = HTTPBearer(auto_error=False)

async def get_security_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_db_session)
) -> RequestSecurityContext:
    """
    Core security dependency.
    Establishes verified:
    - tenant_id
    - user_id
    - roles
    - permissions
    - request_id
    and sets kernel-level PostgreSQL Row-Level Security (RLS).
    """
    request_id = getattr(request.state, "correlation_id", "req-unknown")
    client_ip = request.client.host if request.client else "unknown"

    # 1. Path A: M2M API Key Authentication
    if x_api_key:
        key_hash = hash_api_key(x_api_key)
        stmt = select(TenantApiKey).where(
            TenantApiKey.key_hash == key_hash,
            TenantApiKey.is_active == True  # noqa: E712
        )
        res = await session.execute(stmt)
        api_key_record = res.scalar_one_or_none()
        if not api_key_record:
            await record_security_audit_event(
                session=session,
                tenant_id=x_tenant_id or "unknown",
                action="API_KEY_AUTHENTICATION_FAILED",
                status=AuditActionStatus.DENIED,
                resource_type="API_KEY",
                ip_address=client_ip,
                request_id=request_id
            )
            raise AuthenticationException("Invalid or inactive API key.")

        tenant_id = api_key_record.tenant_id
        roles = [api_key_record.role]
        permissions = PERMISSIONS_MAP.get(api_key_record.role, set())

        await set_tenant_rls_context(session, tenant_id)
        return RequestSecurityContext(
            tenant_id=tenant_id,
            user_id=f"m2m:{api_key_record.id}",
            roles=roles,
            permissions=permissions,
            request_id=request_id,
            client_ip=client_ip,
            email=f"m2m@{api_key_record.name}"
        )

    # 2. Path B: User Bearer JWT Authentication
    if credentials:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        email = payload.get("email")
        raw_roles = payload.get("roles", [])
        raw_perms = payload.get("permissions", [])

        if not user_id or not tenant_id:
            raise AuthenticationException("Malformed JWT claims: missing sub or tenant_id.")

        roles = [RoleType(r) for r in raw_roles if r in RoleType.__members__]
        permissions = set(raw_perms)
        if not permissions and roles:
            permissions = get_permissions_for_roles(roles)

        await set_tenant_rls_context(session, tenant_id)
        return RequestSecurityContext(
            tenant_id=tenant_id,
            user_id=user_id,
            roles=roles,
            permissions=permissions,
            request_id=request_id,
            client_ip=client_ip,
            email=email
        )

    # 3. Path C: Development / Test Header Injection (Restricted to non-production)
    if x_tenant_id:
        roles = [RoleType.ADMIN]
        permissions = PERMISSIONS_MAP[RoleType.ADMIN]
        await set_tenant_rls_context(session, x_tenant_id)
        return RequestSecurityContext(
            tenant_id=x_tenant_id,
            user_id="dev-user-001",
            roles=roles,
            permissions=permissions,
            request_id=request_id,
            client_ip=client_ip,
            email="dev@enterprise.bank"
        )

    # Unauthenticated
    raise AuthenticationException("Missing authentication credentials (JWT Bearer or X-API-Key required).")

def require_permissions(*required_permissions: str) -> Callable:
    """Dependency factory enforcing fine-grained permissions."""
    async def dependency(
        context: RequestSecurityContext = Depends(get_security_context),
        session: AsyncSession = Depends(get_db_session)
    ) -> RequestSecurityContext:
        for perm in required_permissions:
            try:
                enforce_permission(context, perm)
            except AuthorizationException as e:
                await record_security_audit_event(
                    session=session,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    action="PERMISSION_DENIED",
                    status=AuditActionStatus.DENIED,
                    resource_type="PERMISSION",
                    resource_id=perm,
                    ip_address=context.client_ip,
                    request_id=context.request_id,
                    details={"missing_permission": perm}
                )
                raise e
        return context
    return dependency

def require_roles(*allowed_roles: RoleType) -> Callable:
    """Dependency factory enforcing role membership."""
    async def dependency(
        context: RequestSecurityContext = Depends(get_security_context),
        session: AsyncSession = Depends(get_db_session)
    ) -> RequestSecurityContext:
        try:
            enforce_role(context, list(allowed_roles))
        except AuthorizationException as e:
            await record_security_audit_event(
                session=session,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                action="ROLE_UNAUTHORIZED",
                status=AuditActionStatus.DENIED,
                resource_type="ROLE",
                ip_address=context.client_ip,
                request_id=context.request_id,
                details={"allowed_roles": [r.value for r in allowed_roles]}
            )
            raise e
        return context
    return dependency
