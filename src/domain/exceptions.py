from typing import Any


class BaseAppException(Exception):
    """Base exception for all application domain errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "INTERNAL_SERVER_ERROR",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


class EntityNotFoundException(BaseAppException):
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(
            message=f"{entity_name} with ID '{entity_id}' was not found.",
            status_code=404,
            error_code="ENTITY_NOT_FOUND",
            details={"entity_name": entity_name, "entity_id": entity_id},
        )


class TenantIsolationViolationException(BaseAppException):
    def __init__(self, message: str = "Access across tenant boundaries is strictly forbidden."):
        super().__init__(message=message, status_code=403, error_code="TENANT_ISOLATION_VIOLATION")


class AuthenticationException(BaseAppException):
    def __init__(self, message: str = "Invalid or expired credentials."):
        super().__init__(message=message, status_code=401, error_code="AUTHENTICATION_FAILED")


class AuthorizationException(BaseAppException):
    def __init__(self, message: str = "User does not have necessary permissions for this action."):
        super().__init__(message=message, status_code=403, error_code="PERMISSION_DENIED")


class RateLimitExceededException(BaseAppException):
    def __init__(self, retry_after: int = 60, message: str = "Rate limit quota exceeded."):
        super().__init__(
            message=message,
            status_code=429,
            error_code="RATE_LIMIT_EXCEEDED",
            details={"retry_after_seconds": retry_after},
        )


class GuardrailViolationException(BaseAppException):
    def __init__(self, message: str, violations: list | None = None):
        super().__init__(
            message=message,
            status_code=400,
            error_code="AI_GUARDRAIL_VIOLATION",
            details={"violations": violations or []},
        )


class HITLInterruptException(BaseAppException):
    def __init__(self, task_id: str, reason: str):
        super().__init__(
            message="Workflow halted at Human-in-the-Loop review gate.",
            status_code=202,
            error_code="AWAITING_HUMAN_APPROVAL",
            details={"hitl_task_id": task_id, "trigger_reason": reason},
        )


class OptimisticConcurrencyException(BaseAppException):
    def __init__(
        self,
        entity_name: str,
        entity_id: str,
        expected_version: int,
        message: str | None = None,
    ):
        msg = (
            message
            or f"Concurrent update conflict: {entity_name} '{entity_id}' was modified by another transaction (expected version {expected_version})."
        )
        super().__init__(
            message=msg,
            status_code=409,
            error_code="OPTIMISTIC_CONCURRENCY_CONFLICT",
            details={
                "entity_name": entity_name,
                "entity_id": entity_id,
                "expected_version": expected_version,
            },
        )

