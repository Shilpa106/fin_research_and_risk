
from ..domain.entities import RoleType
from ..domain.exceptions import AuthorizationException
from .context import RequestSecurityContext

# ==============================================================================
# Canonical Permission Matrix
# ==============================================================================
PERMISSIONS_MAP: dict[RoleType, set[str]] = {
    RoleType.ADMIN: {
        "*",  # Super-permission across tenant
        "documents:read",
        "documents:write",
        "documents:delete",
        "conversations:read",
        "conversations:write",
        "portfolios:read",
        "portfolios:write",
        "portfolios:delete",
        "risk:execute",
        "hitl:review",
        "hitl:approve",
        "tools:execute:research",
        "tools:execute:risk",
        "tools:execute:admin",
        "users:manage",
        "roles:assign",
        "audit:read",
        "evaluation:read",
        "evaluation:run",
    },
    RoleType.ADVISOR: {
        "documents:read",
        "conversations:read",
        "conversations:write",
        "portfolios:read",
        "risk:execute",
        "tools:execute:research",
    },
    RoleType.ANALYST: {
        "documents:read",
        "documents:write",
        "conversations:read",
        "conversations:write",
        "portfolios:read",
        "risk:execute",
        "tools:execute:research",
        "tools:execute:risk",
        "evaluation:read",
        "evaluation:run",
    },
    RoleType.RISK_MANAGER: {
        "documents:read",
        "conversations:read",
        "conversations:write",
        "portfolios:read",
        "portfolios:write",
        "risk:execute",
        "hitl:review",
        "hitl:approve",
        "tools:execute:risk",
        "audit:read",
        "evaluation:read",
        "evaluation:run",
    },
    RoleType.READ_ONLY_USER: {
        "documents:read",
        "conversations:read",
        "portfolios:read",
    },
}

def get_permissions_for_roles(roles: list[RoleType]) -> set[str]:
    """Flattens all permissions granted across a list of assigned roles."""
    aggregated: set[str] = set()
    for role in roles:
        perms = PERMISSIONS_MAP.get(role, set())
        aggregated.update(perms)
    return aggregated

def enforce_permission(context: RequestSecurityContext, required_permission: str) -> None:
    """Raises AuthorizationException if context does not satisfy permission."""
    if not context.has_permission(required_permission):
        raise AuthorizationException(
            f"Permission denied. Required: '{required_permission}'."
        )

def enforce_role(context: RequestSecurityContext, allowed_roles: list[RoleType]) -> None:
    """Raises AuthorizationException if context does not match one of allowed roles."""
    if not any(context.has_role(r) for r in allowed_roles) and not context.is_admin():
        allowed_names = [r.value for r in allowed_roles]
        raise AuthorizationException(
            f"Action restricted to roles: {allowed_names}."
        )

def enforce_tenant_isolation(context: RequestSecurityContext, target_tenant_id: str) -> None:
    """
    CRITICAL SECURITY CHECK:
    Guarantees user cannot access resources belonging to a different tenant.
    """
    if context.tenant_id != target_tenant_id:
        raise AuthorizationException(
            f"Tenant isolation breach detected: Request tenant '{context.tenant_id}' cannot access target tenant '{target_tenant_id}'."
        )
