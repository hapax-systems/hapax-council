"""Tests for the circuit breaker module."""

from __future__ import annotations

import time
from pathlib import Path

from shared.circuit_breaker import CircuitBreaker


class TestCircuitBreaker:
    def test_initial_state_allows_attempts(self, tmp_path: Path):
        cb = CircuitBreaker(state_path=tmp_path / "cb.json")
        assert cb.can_attempt("test.check")
        assert cb.remaining_attempts("test.check") == 2

    def test_records_attempt(self, tmp_path: Path):
        cb = CircuitBreaker(state_path=tmp_path / "cb.json")
        cb.record_attempt("test.check")
        assert cb.remaining_attempts("test.check") == 1
        assert cb.can_attempt("test.check")

    def test_trips_at_max(self, tmp_path: Path):
        cb = CircuitBreaker(max_attempts=2, state_path=tmp_path / "cb.json")
        cb.record_attempt("test.check")
        cb.record_attempt("test.check")
        assert not cb.can_attempt("test.check")
        assert cb.is_tripped("test.check")
        assert cb.remaining_attempts("test.check") == 0

    def test_success_resets(self, tmp_path: Path):
        cb = CircuitBreaker(max_attempts=2, state_path=tmp_path / "cb.json")
        cb.record_attempt("test.check")
        cb.record_attempt("test.check", success=True)
        # Success resets attempts to 0.
        assert cb.can_attempt("test.check")
        assert cb.remaining_attempts("test.check") == 2

    def test_manual_reset(self, tmp_path: Path):
        cb = CircuitBreaker(max_attempts=1, state_path=tmp_path / "cb.json")
        cb.record_attempt("test.check")
        assert cb.is_tripped("test.check")
        cb.reset("test.check")
        assert cb.can_attempt("test.check")

    def test_persistence(self, tmp_path: Path):
        state_path = tmp_path / "cb.json"
        cb1 = CircuitBreaker(state_path=state_path)
        cb1.record_attempt("test.check")

        # Load from same file.
        cb2 = CircuitBreaker(state_path=state_path)
        assert cb2.remaining_attempts("test.check") == 1

    def test_window_expiry(self, tmp_path: Path):
        cb = CircuitBreaker(
            max_attempts=1, window_seconds=1, state_path=tmp_path / "cb.json"
        )
        cb.record_attempt("test.check")
        assert cb.is_tripped("test.check")

        # Manually expire the window.
        state = cb._get_state("test.check")
        state.window_start = time.time() - 2  # 2 seconds ago
        assert cb.can_attempt("test.check")

    def test_independent_checks(self, tmp_path: Path):
        cb = CircuitBreaker(max_attempts=1, state_path=tmp_path / "cb.json")
        cb.record_attempt("check.a")
        assert cb.is_tripped("check.a")
        assert cb.can_attempt("check.b")

    def test_status_summary(self, tmp_path: Path):
        cb = CircuitBreaker(max_attempts=2, state_path=tmp_path / "cb.json")
        cb.record_attempt("check.a")
        cb.record_attempt("check.a")
        cb.record_attempt("check.b")

        status = cb.status()
        assert status["check.a"]["tripped"] is True
        assert status["check.a"]["remaining"] == 0
        assert status["check.b"]["tripped"] is False
        assert status["check.b"]["remaining"] == 1
