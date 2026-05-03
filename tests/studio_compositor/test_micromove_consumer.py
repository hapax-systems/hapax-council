"""Tests for agents.studio_compositor.micromove_consumer (cc-task u4 Phase 1).

Pin:
- counter increments per advance, labelled by slot index
- cycle advances slot per advance() call
- atomic state file written with the slot's hint
- 8 advances cover all 8 slots (the live-verification acceptance)
- write failure does NOT block counter increment
- latest_state() round-trips the written record
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.studio_compositor.micromove_consumer import (
    DEFAULT_TICK_INTERVAL_S,
    MicromoveAdvanceConsumer,
    all_slot_indices,
    hapax_micromove_advance_total,
)
from shared.micromove_cycle import MICROMOVE_SLOTS


@pytest.fixture(autouse=True)
def _reset_counter():
    hapax_micromove_advance_total.clear()
    yield
    hapax_micromove_advance_total.clear()


def _counter(slot: int) -> float:
    return hapax_micromove_advance_total.labels(slot=str(slot))._value.get()


class TestPinnedConstants:
    def test_default_tick_interval_is_documented(self) -> None:
        """15s = slower of the two cadences in the cc-task; long enough
        that scrape jitter doesn't double-fire."""
        assert DEFAULT_TICK_INTERVAL_S == 15.0

    def test_all_slot_indices_covers_zero_through_seven(self) -> None:
        assert set(all_slot_indices()) == {0, 1, 2, 3, 4, 5, 6, 7}


class TestAdvance:
    def test_advance_returns_new_action(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        action = consumer.advance()
        assert action.slot in {a.slot for a in MICROMOVE_SLOTS}

    def test_advance_increments_counter_for_new_slot(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        before = _counter(1)
        consumer.advance()
        after = _counter(1)
        # Cycle starts at slot 0; first advance moves to slot 1.
        assert after == before + 1

    def test_advance_advances_cycle(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        before = consumer.cycle.current_slot()
        consumer.advance()
        after = consumer.cycle.current_slot()
        assert after == (before + 1) % len(MICROMOVE_SLOTS)

    def test_advance_writes_state_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / "advance.json"
        consumer = MicromoveAdvanceConsumer(state_path=state_path, clock=lambda: 1717000000.0)
        consumer.advance()
        assert state_path.is_file()
        payload = json.loads(state_path.read_text())
        assert payload["slot"] == 1
        assert payload["name"] == MICROMOVE_SLOTS[1].name
        assert payload["axis"] == MICROMOVE_SLOTS[1].axis
        assert payload["advanced_at"] == 1717000000.0
        assert isinstance(payload["hint"], dict)

    def test_advance_state_carries_compositor_transform(self, tmp_path: Path) -> None:
        """Phase 2 compositor-render bridge reads the hint dict; pin its
        shape for slot 0 (zoom-in) which carries compositor_transform."""
        state_path = tmp_path / "advance.json"
        consumer = MicromoveAdvanceConsumer(state_path=state_path)
        # Advance 8 times to wrap back to slot 0 (zoom-in). Cycle is
        # 0-indexed; tick() advances to 1 first; need 8 advances to
        # land on slot 0 again.
        for _ in range(8):
            consumer.advance()
        payload = json.loads(state_path.read_text())
        assert payload["slot"] == 0
        assert payload["name"] == "zoom-in"
        assert "compositor_transform" in payload["hint"]


class TestEightAdvancesCoverAllSlots:
    """Acceptance: live verification expects ≥6 of 8 slots to fire after
    5 min. Validate stronger here — 8 advances cover all 8 slots exactly
    once."""

    def test_eight_advances_cover_all_slots_once(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        for _ in range(8):
            consumer.advance()
        for slot in range(8):
            assert _counter(slot) == 1, f"slot {slot} did not fire exactly once"

    def test_sixteen_advances_cycle_twice(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        for _ in range(16):
            consumer.advance()
        for slot in range(8):
            assert _counter(slot) == 2

    def test_seven_advances_skip_starting_slot(self, tmp_path: Path) -> None:
        """Cycle starts at slot 0; first advance moves to slot 1, so 7
        advances cover slots 1-7 — slot 0 is the starting position not
        a fired-into one until the 8th advance."""
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        for _ in range(7):
            consumer.advance()
        for slot in range(1, 8):
            assert _counter(slot) == 1
        assert _counter(0) == 0


class TestWriteFailureFallback:
    """If state-file write fails, counter MUST still increment so
    Grafana can flag the broken state path independent of the metrics
    pipeline."""

    def test_oserror_during_write_does_not_block_counter(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        with patch("agents.studio_compositor.micromove_consumer._atomic_write_json") as mock_write:
            mock_write.side_effect = OSError("/dev/shm not mounted")
            consumer.advance()
        # Counter still incremented (advance returned cleanly).
        assert _counter(1) == 1


class TestLatestState:
    def test_latest_state_round_trips(self, tmp_path: Path) -> None:
        state_path = tmp_path / "advance.json"
        consumer = MicromoveAdvanceConsumer(state_path=state_path, clock=lambda: 1717000000.0)
        consumer.advance()
        latest = consumer.latest_state()
        assert latest is not None
        assert latest["slot"] == 1
        assert latest["advanced_at"] == 1717000000.0

    def test_latest_state_when_file_missing_is_none(self, tmp_path: Path) -> None:
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "never-written.json")
        assert consumer.latest_state() is None

    def test_latest_state_with_corrupt_json_is_none(self, tmp_path: Path) -> None:
        state_path = tmp_path / "advance.json"
        state_path.write_text("not-json{")
        consumer = MicromoveAdvanceConsumer(state_path=state_path)
        assert consumer.latest_state() is None


class TestThreadSafety:
    """The cycle is locked internally; concurrent advance() calls produce
    distinct slot increments — no two calls land on the same slot."""

    def test_concurrent_advances_produce_distinct_slots(self, tmp_path: Path) -> None:
        import threading

        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        results: list[int] = []
        results_lock = threading.Lock()

        def worker() -> None:
            action = consumer.advance()
            with results_lock:
                results.append(action.slot)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 8 advances on a fresh cycle hit every slot exactly once.
        assert sorted(results) == [0, 1, 2, 3, 4, 5, 6, 7]


class TestAtomicWritePath:
    """The state file path is held by /dev/shm/hapax-compositor/ in
    production; tests use tmp_path. Pin that the consumer creates the
    parent dir if missing."""

    def test_consumer_creates_parent_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "sub" / "dir" / "advance.json"
        consumer = MicromoveAdvanceConsumer(state_path=nested)
        consumer.advance()
        assert nested.is_file()

    def test_clock_default_is_time_time(self, tmp_path: Path) -> None:
        """Construction without explicit clock uses time.time. This pins
        the production code path against accidental fixture leakage."""
        consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "advance.json")
        before = time.time()
        consumer.advance()
        after = time.time()
        latest = consumer.latest_state()
        assert latest is not None
        assert before <= float(latest["advanced_at"]) <= after
