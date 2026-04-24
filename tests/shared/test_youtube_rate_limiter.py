"""Unit tests for the per-endpoint daily quota bucket."""

from __future__ import annotations

import tempfile
from pathlib import Path

from shared.youtube_rate_limiter import QuotaBucket


def test_default_budget_allows_small_calls():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        bucket = QuotaBucket(state_path=state)
        assert bucket.try_acquire("thumbnails.set", cost=50)


def test_budget_exhaustion():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        bucket = QuotaBucket(
            state_path=state,
            endpoint_budgets={"test.endpoint": 100},
        )
        assert bucket.try_acquire("test.endpoint", cost=60)
        assert bucket.try_acquire("test.endpoint", cost=40)
        assert not bucket.try_acquire("test.endpoint", cost=1)


def test_persistence_across_instances():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        first = QuotaBucket(
            state_path=state,
            endpoint_budgets={"test.endpoint": 100},
        )
        assert first.try_acquire("test.endpoint", cost=60)

        second = QuotaBucket(
            state_path=state,
            endpoint_budgets={"test.endpoint": 100},
        )
        assert second.remaining("test.endpoint") == 40


def test_unknown_endpoint_falls_back_to_default():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        bucket = QuotaBucket(state_path=state, daily_cap=1000)
        assert bucket.try_acquire("brand-new.endpoint", cost=40)
        # Default bucket = max(50, 1000//20) = 50.
        assert bucket.remaining("brand-new.endpoint") == 10


def test_state_file_corrupt_starts_fresh():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        state.write_text("{not json")
        bucket = QuotaBucket(state_path=state)
        # Should not raise; should still allow normal calls.
        assert bucket.try_acquire("thumbnails.set", cost=50)
