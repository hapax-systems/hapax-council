"""Generic circuit breaker for external service calls."""

from __future__ import annotations

import logging
import time
from typing import Literal

log = logging.getLogger(__name__)


class CircuitBreaker:
    """Three-state circuit breaker: closed -> open -> half_open -> closed.

    - closed: all requests pass, failures counted
    - open: all requests rejected, wait cooldown_s
    - half_open: one probe request allowed; success closes, failure reopens
    """

    def __init__(self, name: str, failure_threshold: int = 5, cooldown_s: float = 60.0) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._failures = 0
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._opened_at: float = 0.0

    def allow_request(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self._cooldown_s:
                self._state = "half_open"
                log.info("Circuit breaker '%s' half-open (probing)", self._name)
                return True
            return False
        return True

    def record_success(self) -> None:
        if self._state == "half_open":
            log.info("Circuit breaker '%s' closed (probe succeeded)", self._name)
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == "half_open":
            self._state = "open"
            self._opened_at = time.monotonic()
            log.warning("Circuit breaker '%s' re-opened (probe failed)", self._name)
        elif self._failures >= self._failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()
            log.warning("Circuit breaker '%s' opened after %d failures", self._name, self._failures)

    @property
    def is_open(self) -> bool:
        return self._state == "open"

    @property
    def consecutive_failures(self) -> int:
        return self._failures
