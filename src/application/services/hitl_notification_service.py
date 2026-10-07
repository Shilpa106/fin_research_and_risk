import logging
from datetime import datetime
from typing import Any

from ...domain.entities import HITLReviewTask, RoleType

logger = logging.getLogger("enterprise_copilot.hitl.notification")


class HITLNotificationService:
    """
    Enterprise Notification Dispatcher for Human-in-the-Loop approval requests.
    Dispatches alerts to Senior Risk Officers and Administrators when high-impact
    financial thresholds or state modifications are intercepted.
    """

    def __init__(self):
        # In-memory notification journal for telemetry and test verification
        self._sent_notifications: list[dict[str, Any]] = []

    async def notify_reviewers(
        self,
        task: HITLReviewTask,
        target_roles: list[RoleType] | None = None,
    ) -> dict[str, Any]:
        """
        Dispatches notification alerts to authorized reviewer groups.
        """
        roles = target_roles or [RoleType.RISK_MANAGER, RoleType.ADMIN]
        notification_payload = {
            "notification_id": f"notif-{task.id[:8]}",
            "task_id": task.id,
            "tenant_id": task.tenant_id,
            "target_roles": [r.value for r in roles],
            "reason": task.reason,
            "risk_score": task.risk_score,
            "proposed_action": task.proposed_action,
            "created_at": task.created_at.isoformat() if task.created_at else datetime.utcnow().isoformat(),
            "expires_at": task.expires_at.isoformat() if task.expires_at else None,
            "status": "DISPATCHED",
        }
        self._sent_notifications.append(notification_payload)
        logger.info(
            f"HITL Notification dispatched for task '{task.id}' (Tenant: '{task.tenant_id}', Roles: {roles})"
        )
        return notification_payload

    def get_dispatched_notifications(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """Returns dispatched notifications, optionally filtered by tenant."""
        if tenant_id:
            return [n for n in self._sent_notifications if n["tenant_id"] == tenant_id]
        return list(self._sent_notifications)

    def clear(self) -> None:
        """Clears notification journal (for test isolation)."""
        self._sent_notifications.clear()
