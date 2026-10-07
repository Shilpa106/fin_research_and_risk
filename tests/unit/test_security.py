import pytest

from src.domain.entities import RoleType
from src.domain.exceptions import AuthenticationException, AuthorizationException
from src.security.auth import (
    create_access_token,
    create_refresh_token_string,
    decode_access_token,
    hash_api_key,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from src.security.context import RequestSecurityContext
from src.security.rbac import (
    PERMISSIONS_MAP,
    enforce_permission,
    enforce_role,
    enforce_tenant_isolation,
)


@pytest.mark.unit
def test_password_hashing_and_verification():
    """Verify PBKDF2 password hashing and constant-time verification."""
    password = "SuperSecurePassword123!"
    hashed = hash_password(password)
    assert hashed != password
    assert "$" in hashed
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


@pytest.mark.unit
def test_jwt_access_token_creation_and_decoding():
    """Verify JWT access token generation and cryptographic claims decoding."""
    payload = {
        "sub": "user-uuid-123",
        "tenant_id": "tenant-uuid-456",
        "roles": [RoleType.ANALYST.value],
        "permissions": list(PERMISSIONS_MAP[RoleType.ANALYST]),
        "email": "analyst@wallstreet.bank",
    }
    token = create_access_token(payload)
    assert isinstance(token, str)

    decoded = decode_access_token(token)
    assert decoded["sub"] == "user-uuid-123"
    assert decoded["tenant_id"] == "tenant-uuid-456"
    assert RoleType.ANALYST.value in decoded["roles"]
    assert "documents:read" in decoded["permissions"]
    assert "exp" in decoded


@pytest.mark.unit
def test_invalid_jwt_token_raises_authentication_exception():
    """Verify tampering with JWT signature raises AuthenticationException."""
    with pytest.raises(AuthenticationException):
        decode_access_token("invalid.jwt.token.string")


@pytest.mark.unit
def test_rbac_permission_enforcement():
    """Verify fine-grained permission enforcement via RequestSecurityContext."""
    analyst_context = RequestSecurityContext(
        tenant_id="tenant-1",
        user_id="user-1",
        roles=[RoleType.ANALYST],
        permissions=PERMISSIONS_MAP[RoleType.ANALYST],
        request_id="req-1",
    )
    # Analyst can read documents
    enforce_permission(analyst_context, "documents:read")
    enforce_permission(analyst_context, "documents:write")

    # Analyst cannot execute admin tools or assign roles
    with pytest.raises(AuthorizationException):
        enforce_permission(analyst_context, "roles:assign")

    read_only_context = RequestSecurityContext(
        tenant_id="tenant-1",
        user_id="user-2",
        roles=[RoleType.READ_ONLY_USER],
        permissions=PERMISSIONS_MAP[RoleType.READ_ONLY_USER],
        request_id="req-2",
    )
    # Read-only user cannot write documents
    with pytest.raises(AuthorizationException):
        enforce_permission(read_only_context, "documents:write")


@pytest.mark.unit
def test_rbac_role_enforcement():
    """Verify role checks via RequestSecurityContext."""
    risk_manager_context = RequestSecurityContext(
        tenant_id="tenant-1",
        user_id="user-rm",
        roles=[RoleType.RISK_MANAGER],
        permissions=PERMISSIONS_MAP[RoleType.RISK_MANAGER],
        request_id="req-3",
    )
    enforce_role(risk_manager_context, [RoleType.RISK_MANAGER, RoleType.ADMIN])

    with pytest.raises(AuthorizationException):
        enforce_role(risk_manager_context, [RoleType.ADMIN])


@pytest.mark.unit
def test_tenant_isolation_enforcement():
    """Verify strict tenant isolation assertion."""
    context = RequestSecurityContext(
        tenant_id="tenant-alpha",
        user_id="user-alpha",
        roles=[RoleType.ADMIN],
        permissions=PERMISSIONS_MAP[RoleType.ADMIN],
        request_id="req-4",
    )
    # Same tenant passes
    enforce_tenant_isolation(context, "tenant-alpha")

    # Cross-tenant access fails immediately
    with pytest.raises(AuthorizationException):
        enforce_tenant_isolation(context, "tenant-beta")


@pytest.mark.unit
def test_refresh_token_generation_and_hashing():
    """Verify secure random refresh token string and SHA-256 hash."""
    raw_token = create_refresh_token_string()
    assert len(raw_token) > 40
    token_hash = hash_refresh_token(raw_token)
    assert len(token_hash) == 64
    assert hash_refresh_token(raw_token) == token_hash


@pytest.mark.unit
def test_api_key_hashing():
    """Verify deterministic SHA-256 hashing for API keys."""
    raw_key = "fin_copilot_sec_abc123xyz"
    hashed = hash_api_key(raw_key)
    assert len(hashed) == 64
    assert hash_api_key(raw_key) == hashed

