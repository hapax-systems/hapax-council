"""Circuit breaker wrapper for capability adapters.

Wraps any adapter with Closed/Open/Half-Open circuit breaker semantics.
Prevents cascading failures when an external service goes down.

States:
  - Closed: normal operation, failures counted
  - Open: all calls short-circuit, waiting for reset timeout
  - Half-Open: one probe call allowed to test recovery
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from shared.capabilities.protocols import HealthStatus

log = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 3  # failures before opening
    reset_timeout_s: float = 30.0  # seconds in open state before half-open
    half_open_max_calls: int = 1  # calls allowed in half-open


class CircuitBreaker:
    """Circuit breaker wrapper for capability adapters.

    Wraps the health() and available() methods of any adapter. When
    failures exceed the threshold, the circuit opens and all calls
    return unhealthy until the reset timeout expires.
    """

    def __init__(
        self,
        adapter: object,
        *,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self._adapter = adapter
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    @property
    def adapter(self) -> object:
        return self._adapter

    @property
    def state(self) -> CircuitState:
        self._check_reset()
        return self._state

    @property
    def name(self) -> str:
        return getattr(self._adapter, "name", type(self._adapter).__name__)

    def _check_reset(self) -> None:
        """Transition from Open → Half-Open if reset timeout has elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.reset_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                log.info("Circuit breaker %s: open → half-open", self.name)

    def _record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            log.info("Circuit breaker %s: half-open → closed", self.name)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def _record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            log.warning("Circuit breaker %s: half-open → open", self.name)
        elif self._failure_count >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
            log.warning(
                "Circuit breaker %s: closed → open (failures=%d)",
                self.name,
                self._failure_count,
            )

    def available(self) -> bool:
        """Check availability, respecting circuit state."""
        self._check_reset()
        if self._state == CircuitState.OPEN:
            return False
        try:
            result = self._adapter.available()  # type: ignore[union-attr]
            if result:
                self._record_success()
            else:
                self._record_failure()
            return result
        except Exception:
            self._record_failure()
            return False

    def health(self) -> HealthStatus:
        """Check health, respecting circuit state."""
        self._check_reset()
        if self._state == CircuitState.OPEN:
            return HealthStatus(
                healthy=False,
                message=f"Circuit open (failures={self._failure_count})",
            )
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls > self._config.half_open_max_calls:
                return HealthStatus(
                    healthy=False,
                    message="Circuit half-open, probe limit reached",
                )
        try:
            result = self._adapter.health()  # type: ignore[union-attr]
            if result.healthy:
                self._record_success()
            else:
                self._record_failure()
            return result
        except Exception as e:
            self._record_failure()
            return HealthStatus(healthy=False, message=str(e))
