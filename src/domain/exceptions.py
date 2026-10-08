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


class ProviderTimeoutException(BaseAppException):
    def __init__(self, provider: str, model: str, timeout_seconds: float):
        super().__init__(
            message=f"Model call to provider '{provider}' (model: '{model}') timed out after {timeout_seconds}s.",
            status_code=504,
            error_code="GATEWAY_TIMEOUT",
            details={"provider": provider, "model": model, "timeout_seconds": timeout_seconds},
        )


class ProviderUnavailableException(BaseAppException):
    def __init__(self, provider: str, model: str, reason: str = "Service unavailable"):
        super().__init__(
            message=f"LLM provider '{provider}' (model: '{model}') is currently unavailable: {reason}",
            status_code=503,
            error_code="SERVICE_UNAVAILABLE",
            details={"provider": provider, "model": model, "reason": reason},
        )


class CircuitBreakerOpenException(BaseAppException):
    def __init__(self, provider: str, model: str):
        super().__init__(
            message=f"Circuit breaker is OPEN for provider '{provider}' (model: '{model}'). Request rejected.",
            status_code=503,
            error_code="CIRCUIT_BREAKER_OPEN",
            details={"provider": provider, "model": model},
        )


class TokenBudgetExceededException(BaseAppException):
    def __init__(self, tenant_id: str, requested_tokens: int, remaining_budget: int):
        super().__init__(
            message=f"Token budget exceeded for tenant '{tenant_id}'. Requested: {requested_tokens}, Remaining: {remaining_budget}.",
            status_code=429,
            error_code="TOKEN_BUDGET_EXCEEDED",
            details={"tenant_id": tenant_id, "requested_tokens": requested_tokens, "remaining_budget": remaining_budget},
        )


class CostLimitExceededException(BaseAppException):
    def __init__(self, tenant_id: str, accumulated_cost: float, cost_limit: float):
        super().__init__(
            message=f"Monthly cost limit of ${cost_limit:.2f} exceeded for tenant '{tenant_id}' (Accumulated: ${accumulated_cost:.2f}).",
            status_code=429,
            error_code="COST_LIMIT_EXCEEDED",
            details={"tenant_id": tenant_id, "accumulated_cost": accumulated_cost, "cost_limit": cost_limit},
        )


class ToolNotFoundException(BaseAppException):
    def __init__(self, tool_name: str):
        super().__init__(
            message=f"MCP Tool '{tool_name}' was not found in registered tool catalog.",
            status_code=404,
            error_code="TOOL_NOT_FOUND",
            details={"tool_name": tool_name},
        )


class ToolValidationException(BaseAppException):
    def __init__(self, tool_name: str, errors: dict[str, Any] | list[Any]):
        super().__init__(
            message=f"Schema validation failed for MCP tool '{tool_name}'.",
            status_code=422,
            error_code="TOOL_VALIDATION_ERROR",
            details={"tool_name": tool_name, "validation_errors": errors},
        )


class ToolExecutionTimeoutException(BaseAppException):
    def __init__(self, tool_name: str, timeout_seconds: float):
        super().__init__(
            message=f"Execution of MCP tool '{tool_name}' timed out after {timeout_seconds}s.",
            status_code=504,
            error_code="TOOL_EXECUTION_TIMEOUT",
            details={"tool_name": tool_name, "timeout_seconds": timeout_seconds},
        )


class MaliciousInputDetectedException(BaseAppException):
    def __init__(self, tool_name: str, violation_type: str, details: str):
        super().__init__(
            message=f"Malicious input detected in call to tool '{tool_name}': {violation_type}",
            status_code=400,
            error_code="MALICIOUS_INPUT_DETECTED",
            details={"tool_name": tool_name, "violation_type": violation_type, "evidence": details},
        )


class EvaluationRegressionException(BaseAppException):
    def __init__(self, message: str, breaches: list[dict[str, Any]] | None = None):
        super().__init__(
            message=message,
            status_code=422,
            error_code="EVALUATION_REGRESSION_DETECTED",
            details={"breaches": breaches or []},
        )




