import enum
import logging
import time

logger = logging.getLogger("enterprise_copilot.ai_gateway.circuit_breaker")


class CircuitState(str, enum.Enum):
    """Circuit breaker operational state."""
    CLOSED = "CLOSED"      # Normal operation: requests pass through
    OPEN = "OPEN"          # Tripped: requests immediately fail/fallback
    HALF_OPEN = "HALF_OPEN"  # Testing: limited probe requests allowed


class CircuitBreaker:
    """
    Stateful circuit breaker protecting downstream foundation model providers.
    Prevents cascading service degradation by tripping when failure thresholds are met.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        half_open_max_trials: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_trials = half_open_max_trials

        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at: float | None = None
        self.half_open_trials = 0

    def is_allowed(self) -> bool:
        """Determines whether a call to the underlying provider is permitted."""
        now = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if self.opened_at is not None and (now - self.opened_at) >= self.recovery_timeout:
                logger.info(
                    "Circuit breaker '%s' transition: OPEN -> HALF_OPEN (recovery timeout %.1fs elapsed)",
                    self.name,
                    self.recovery_timeout,
                )
                self.state = CircuitState.HALF_OPEN
                self.half_open_trials = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_trials < self.half_open_max_trials:
                self.half_open_trials += 1
                return True
            return False

        return False

    def record_success(self) -> None:
        """Records a successful provider call."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker '%s' transition: HALF_OPEN -> CLOSED (probe succeeded)", self.name)
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            self.half_open_trials = 0
        elif self.state == CircuitState.CLOSED:
            self.consecutive_failures = 0

    def record_failure(self) -> None:
        """Records a failed provider call and trips circuit if threshold reached."""
        self.consecutive_failures += 1

        if self.state == CircuitState.HALF_OPEN:
            logger.warning("Circuit breaker '%s' transition: HALF_OPEN -> OPEN (probe failed)", self.name)
            self.state = CircuitState.OPEN
            self.opened_at = time.time()
        elif self.state == CircuitState.CLOSED:
            if self.consecutive_failures >= self.failure_threshold:
                logger.warning(
                    "Circuit breaker '%s' transition: CLOSED -> OPEN (threshold %d reached)",
                    self.name,
                    self.failure_threshold,
                )
                self.state = CircuitState.OPEN
                self.opened_at = time.time()

    def reset(self) -> None:
        """Manually forces the circuit breaker back to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at = None
        self.half_open_trials = 0
