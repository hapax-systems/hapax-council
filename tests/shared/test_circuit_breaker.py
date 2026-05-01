"""Tests for shared.circuit_breaker.CircuitBreaker.

Three-state breaker:
- ``closed``  — requests pass, failures counted
- ``open``    — requests rejected until ``cooldown_s`` elapses
- ``half_open`` — one probe; success → closed, failure → open

Tests use ``unittest.mock.patch`` to drive ``time.monotonic`` so
the cooldown transition is deterministic without actual sleeps.
"""

from __future__ import annotations

from unittest.mock import patch

from shared.circuit_breaker import CircuitBreaker


class TestInitialState:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker("test")
        assert not cb.is_open
        assert cb.allow_request()
        assert cb.consecutive_failures == 0


class TestFailureCounting:
    def test_below_threshold_stays_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open
        assert cb.allow_request()
        assert cb.consecutive_failures == 2

    def test_at_threshold_opens(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open
        assert not cb.allow_request()

    def test_record_success_resets_failures(self) -> None:
        """Mid-streak success clears the failure counter and stays closed."""
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.consecutive_failures == 0
        assert not cb.is_open
        assert cb.allow_request()


class TestOpenStateRejects:
    def test_open_state_rejects_until_cooldown(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_s=10.0)
        with patch("shared.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            cb.record_failure()
            assert cb.is_open
            # Just before cooldown elapses — still rejecting.
            mock_time.monotonic.return_value = 109.9
            assert not cb.allow_request()


class TestCooldownExpiry:
    def test_cooldown_elapsed_transitions_to_half_open(self) -> None:
        """After cooldown_s, the next allow_request flips to half_open
        and returns True (one probe permitted)."""
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_s=10.0)
        with patch("shared.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            cb.record_failure()
            mock_time.monotonic.return_value = 110.5  # past cooldown
            assert cb.allow_request()
            # State is now half_open; further allow_request still True
            assert cb.allow_request()
            # is_open property returns False in half_open state
            assert not cb.is_open


class TestHalfOpenTransitions:
    def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_s=10.0)
        with patch("shared.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            cb.record_failure()
            mock_time.monotonic.return_value = 200.0
            cb.allow_request()  # → half_open
            cb.record_success()
            assert not cb.is_open
            assert cb.allow_request()
            assert cb.consecutive_failures == 0

    def test_half_open_failure_reopens(self) -> None:
        """A failure during half-open probing reopens the breaker
        and resets the cooldown clock to that moment."""
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_s=10.0)
        with patch("shared.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            cb.record_failure()
            mock_time.monotonic.return_value = 200.0
            cb.allow_request()  # → half_open
            cb.record_failure()  # → open again
            assert cb.is_open
            # New cooldown window starts at 200.0 (record_failure time)
            mock_time.monotonic.return_value = 209.9
            assert not cb.allow_request()
            mock_time.monotonic.return_value = 210.5
            assert cb.allow_request()  # cooldown elapsed
