from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppSettings, get_settings
from ..domain.exceptions import AuthenticationException, TenantIsolationViolationException
from ..infrastructure.database import get_db_session, set_tenant_rls_context
from ..infrastructure.redis import get_redis_client
from ..security.auth import decode_access_token

security_bearer = HTTPBearer(auto_error=False)


def get_app_settings() -> AppSettings:
    """Dependency for injecting immutable application settings."""
    return get_settings()


async def get_database_session(session: AsyncSession = Depends(get_db_session)) -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding pooled database session."""
    yield session


def get_redis() -> aioredis.Redis:
    """Dependency for injecting async Redis client."""
    return get_redis_client()


async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
) -> dict | None:
    """Decodes Bearer JWT token if provided."""
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except AuthenticationException as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=e.message, headers={"WWW-Authenticate": "Bearer"}
        ) from e


async def get_current_tenant_id(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    token_payload: dict | None = Depends(get_current_token_payload),
    session: AsyncSession = Depends(get_database_session),
) -> str:
    """
    Resolves tenant context from header or authenticated JWT.
    Enforces PostgreSQL Row-Level Security session context.
    """
    resolved_tenant = None
    if token_payload and "tenant_id" in token_payload:
        resolved_tenant = token_payload["tenant_id"]
    elif x_tenant_id:
        resolved_tenant = x_tenant_id

    if not resolved_tenant:
        raise TenantIsolationViolationException("Tenant context is required (missing X-Tenant-ID or JWT claim).")

    # Enforce RLS on active DB session
    await set_tenant_rls_context(session, resolved_tenant)
    return resolved_tenant
