from dataclasses import dataclass, field

from ..domain.entities import RoleType


@dataclass
class RequestSecurityContext:
    """
    Unified security context established for every protected request.
    Enforces strict tenant boundary, user identity, roles, and fine-grained permissions.
    """
    tenant_id: str
    user_id: str
    roles: list[RoleType] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    request_id: str = "unknown"
    client_ip: str | None = None
    email: str | None = None

    def has_permission(self, permission: str) -> bool:
        """Checks if context holds permission or wildcard."""
        return "*" in self.permissions or permission in self.permissions

    def has_role(self, role: RoleType) -> bool:
        """Checks if context holds specific role."""
        return role in self.roles

    def is_admin(self) -> bool:
        """Shortcut for tenant administrative privilege."""
        return RoleType.ADMIN in self.roles or "*" in self.permissions
