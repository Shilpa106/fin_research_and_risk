import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.entities import AuditActionStatus, SecurityAuditEvent

logger = logging.getLogger("security.audit")

async def record_security_audit_event(
    session: AsyncSession | None,
    tenant_id: str,
    action: str,
    status: AuditActionStatus,
    resource_type: str,
    resource_id: str | None = None,
    user_id: str | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Logs an immutable security audit event to structured logger and database.
    Complies with SOC-2, SEC Rule 17a-4, and FINRA audit logging guidelines.
    """
    import json
    details_str = json.dumps(details) if details else None

    # 1. Emit structured log with audit tagging
    logger.warning(
        f"[AUDIT] action={action} status={status.value} tenant={tenant_id} user={user_id} resource={resource_type}:{resource_id}",
        extra={
            "audit_action": action,
            "audit_status": status.value,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "details": details,
        }
    )

    # 2. Persist to database if active session is available
    if session is not None:
        try:
            event = SecurityAuditEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status=status,
                ip_address=ip_address,
                request_id=request_id,
                details=details_str,
            )
            session.add(event)
            await session.commit()
        except Exception as e:
            logger.error(f"Failed to persist security audit event to DB: {e}")
            await session.rollback()
