from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ....application.services.auth_service import AuthService
from ....domain.entities import RoleType
from ....infrastructure.database import get_db_session
from ....security.context import RequestSecurityContext
from ....security.guards import get_security_context, require_roles

router = APIRouter(prefix="/auth", tags=["Identity & Authentication"])

class LoginPayload(BaseModel):
    email: str
    password: str
    tenant_slug: str

class RefreshPayload(BaseModel):
    refresh_token: str

class RoleAssignPayload(BaseModel):
    target_user_id: str
    new_role: RoleType

@router.post("/token", summary="OAuth2/OIDC Token Endpoint")
async def login_for_access_token(
    payload: LoginPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Authenticates user within tenant boundary and returns access + refresh tokens.
    """
    auth_service = AuthService(session)
    request_id = getattr(request.state, "correlation_id", "req-unknown")
    client_ip = request.client.host if request.client else None

    access_token, refresh_token, tenant_id, user_id, roles = await auth_service.authenticate_user(
        email=payload.email,
        password=payload.password,
        tenant_slug=payload.tenant_slug,
        ip_address=client_ip,
        request_id=request_id
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "tenant_id": tenant_id,
        "user_id": user_id,
        "roles": [r.value for r in roles]
    }

@router.post("/refresh", summary="Rotate Refresh Token")
async def refresh_access_token(
    payload: RefreshPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Exchanges valid refresh token for a new access token and rotated refresh token.
    Detects and blocks token reuse / replay attacks.
    """
    auth_service = AuthService(session)
    request_id = getattr(request.state, "correlation_id", "req-unknown")
    client_ip = request.client.host if request.client else None

    new_access, new_refresh, tenant_id, roles = await auth_service.refresh_session(
        raw_refresh_token=payload.refresh_token,
        ip_address=client_ip,
        request_id=request_id
    )

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "tenant_id": tenant_id,
        "roles": [r.value for r in roles]
    }

@router.get("/me", summary="Get Current Security Context")
async def get_current_user_profile(
    context: RequestSecurityContext = Depends(get_security_context)
):
    """Returns established security context for the authenticated caller."""
    return {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "email": context.email,
        "roles": [r.value for r in context.roles],
        "permissions": sorted(context.permissions),
        "request_id": context.request_id
    }

@router.post("/roles/assign", summary="Assign Role to Tenant User")
async def assign_role(
    payload: RoleAssignPayload,
    context: RequestSecurityContext = Depends(require_roles(RoleType.ADMIN)),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Assigns role to a user within tenant.
    Enforces that caller MUST possess ADMIN role (prevents role escalation).
    """
    auth_service = AuthService(session)
    await auth_service.assign_user_role(
        context=context,
        target_user_id=payload.target_user_id,
        new_role=payload.new_role
    )
    return {
        "status": "SUCCESS",
        "target_user_id": payload.target_user_id,
        "assigned_role": payload.new_role.value
    }
