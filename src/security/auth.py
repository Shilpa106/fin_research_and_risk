import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..domain.entities import AuditActionStatus, RefreshToken, RoleType
from ..domain.exceptions import AuthenticationException
from .audit import record_security_audit_event
from .rbac import get_permissions_for_roles


def hash_password(password: str, salt: str | None = None) -> str:
    """Hashes password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    if salt is None:
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    ).hex()
    return f"{salt}${pwd_hash}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plain password against stored salt$hash."""
    try:
        salt, expected_hash = hashed_password.split("$")
        computed_hash = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000
        ).hex()
        return hmac.compare_digest(expected_hash, computed_hash)
    except Exception:
        return False

def create_access_token(
    user_id: str | dict[str, Any],
    tenant_id: str | None = None,
    email: str | None = None,
    roles: list[RoleType] | None = None,
    expires_delta: timedelta | None = None
) -> str:
    """Generates signed JWT access token containing tenant identity, roles, and permissions."""
    settings = get_settings()
    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))

    if isinstance(user_id, dict):
        payload_dict = dict(user_id)
        if "iat" not in payload_dict:
            payload_dict["iat"] = now
        if "exp" not in payload_dict:
            payload_dict["exp"] = expire
        if "iss" not in payload_dict:
            payload_dict["iss"] = "enterprise-copilot-auth"
        return jwt.encode(
            payload_dict,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm
        )

    roles_list = roles or []
    permissions = list(get_permissions_for_roles(roles_list))

    payload = {
        "sub": user_id,
        "tenant_id": tenant_id or "",
        "email": email or "",
        "roles": [r.value if isinstance(r, RoleType) else str(r) for r in roles_list],
        "permissions": permissions,
        "iat": now,
        "exp": expire,
        "iss": "enterprise-copilot-auth",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm
    )

def decode_access_token(token: str) -> dict[str, Any]:
    """Decodes and validates signed JWT token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer="enterprise-copilot-auth",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthenticationException("Access token has expired.") from None
    except jwt.PyJWTError as e:
        raise AuthenticationException(f"Invalid access token: {str(e)}") from e

def hash_token(raw_token: str) -> str:
    """Computes SHA-256 hash for secure token storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

hash_refresh_token = hash_token

def create_refresh_token_string() -> str:
    """Generates a cryptographically random refresh token string."""
    return secrets.token_urlsafe(48)

async def create_refresh_token(
    session: AsyncSession,
    user_id: str,
    tenant_id: str,
    family_id: str | None = None
) -> str:
    """
    Generates a cryptographically random refresh token and records its hash.
    Groups tokens by family_id to detect token replay attacks.
    """
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)
    token_family = family_id or secrets.token_urlsafe(16)
    expires_at = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)

    refresh_entity = RefreshToken(
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=token_hash,
        family_id=token_family,
        expires_at=expires_at,
        is_revoked=False,
    )
    session.add(refresh_entity)
    await session.commit()
    return raw_token

async def rotate_refresh_token(
    session: AsyncSession,
    raw_refresh_token: str,
    request_id: str | None = None,
    ip_address: str | None = None
) -> tuple[str, str, str, list[RoleType]]:
    """
    Executes secure refresh token rotation:
    1. Verifies token existence and expiration.
    2. REPLAY ATTACK DETECTION: If token was already revoked, immediately revokes ENTIRE family.
    3. Revokes current token and issues new token in the same family.
    Returns: (new_access_token, new_refresh_token, tenant_id, roles)
    """
    from ..domain.entities import TenantMembership

    current_hash = hash_token(raw_refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == current_hash)
    result = await session.execute(stmt)
    token_record = result.scalar_one_or_none()

    if not token_record:
        raise AuthenticationException("Invalid refresh token.")

    # REPLAY ATTACK DETECTION
    if token_record.is_revoked:
        # Compromise detected! Revoke all tokens in family
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token_record.family_id)
            .values(is_revoked=True)
        )
        await session.commit()
        await record_security_audit_event(
            session=session,
            tenant_id=token_record.tenant_id,
            user_id=token_record.user_id,
            action="REFRESH_TOKEN_REPLAY_DETECTED",
            status=AuditActionStatus.DENIED,
            resource_type="REFRESH_TOKEN",
            resource_id=token_record.id,
            ip_address=ip_address,
            request_id=request_id,
            details={"family_id": token_record.family_id}
        )
        raise AuthenticationException("Token reuse detected. All sessions in family have been revoked.")

    if token_record.expires_at < datetime.utcnow():
        token_record.is_revoked = True
        await session.commit()
        raise AuthenticationException("Refresh token has expired.")

    # Mark current token revoked
    token_record.is_revoked = True
    await session.commit()

    # Load user roles within tenant
    from sqlalchemy.orm import selectinload
    membership_stmt = (
        select(TenantMembership)
        .options(selectinload(TenantMembership.roles), selectinload(TenantMembership.user))
        .where(
            TenantMembership.tenant_id == token_record.tenant_id,
            TenantMembership.user_id == token_record.user_id,
            TenantMembership.is_active == True  # noqa: E712
        )
    )
    m_result = await session.execute(membership_stmt)
    membership = m_result.scalar_one_or_none()

    if not membership:
        raise AuthenticationException("User tenant membership is inactive or removed.")

    roles = [r.name for r in membership.roles]
    if not roles:
        roles = [RoleType.READ_ONLY_USER]

    # Issue new access token
    new_access_token = create_access_token(
        user_id=token_record.user_id,
        tenant_id=token_record.tenant_id,
        email=membership.user.email if hasattr(membership, "user") else "user@enterprise",
        roles=roles,
    )

    # Issue rotated refresh token
    new_refresh_token = await create_refresh_token(
        session=session,
        user_id=token_record.user_id,
        tenant_id=token_record.tenant_id,
        family_id=token_record.family_id,
    )

    return new_access_token, new_refresh_token, token_record.tenant_id, roles

def hash_api_key(api_key: str) -> str:
    """Deterministic SHA-256 hash for machine-to-machine API key lookup."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
