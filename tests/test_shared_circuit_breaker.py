"""Tests for shared.circuit_breaker."""

import time

from shared.circuit_breaker import CircuitBreaker


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, cooldown_s=1.0)
        assert cb.allow_request() is True
        assert cb.is_open is False

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, cooldown_s=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open is True
        assert cb.allow_request() is False
        assert cb.consecutive_failures == 3

    def test_success_resets_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, cooldown_s=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.consecutive_failures == 0
        assert cb.is_open is False

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_s=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        time.sleep(0.15)
        assert cb.allow_request() is True
        cb.record_failure()
        assert cb.is_open is True

    def test_half_open_success_closes(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_s=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.is_open is False
        assert cb.consecutive_failures == 0
