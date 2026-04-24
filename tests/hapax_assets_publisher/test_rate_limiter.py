"""Tests for agents/hapax_assets_publisher/push_throttle.py — ytb-AUTH-HOSTING."""

from __future__ import annotations

import time
from pathlib import Path

from agents.hapax_assets_publisher.push_throttle import PushThrottle


class TestPushThrottle:
    def test_first_call_allowed(self, tmp_path: Path) -> None:
        pt = PushThrottle(state_file=tmp_path / "state", min_interval_sec=30)
        assert pt.try_acquire() is True

    def test_immediate_second_call_blocked(self, tmp_path: Path) -> None:
        pt = PushThrottle(state_file=tmp_path / "state", min_interval_sec=30)
        assert pt.try_acquire() is True
        assert pt.try_acquire() is False

    def test_call_allowed_after_window(self, tmp_path: Path) -> None:
        pt = PushThrottle(state_file=tmp_path / "state", min_interval_sec=0)
        assert pt.try_acquire() is True
        time.sleep(0.01)
        assert pt.try_acquire() is True

    def test_state_persists_across_instances(self, tmp_path: Path) -> None:
        state = tmp_path / "state"
        pt1 = PushThrottle(state_file=state, min_interval_sec=30)
        assert pt1.try_acquire() is True
        # A fresh instance reading the same file should see the lockout.
        pt2 = PushThrottle(state_file=state, min_interval_sec=30)
        assert pt2.try_acquire() is False

    def test_missing_state_file_starts_clean(self, tmp_path: Path) -> None:
        # state_file doesn't exist yet; try_acquire should succeed on first call.
        pt = PushThrottle(state_file=tmp_path / "nonexistent", min_interval_sec=30)
        assert pt.try_acquire() is True

    def test_corrupt_state_file_recovers(self, tmp_path: Path) -> None:
        state = tmp_path / "state"
        state.write_text("not a timestamp")
        pt = PushThrottle(state_file=state, min_interval_sec=30)
        # Recovery: treat unparseable state as "never acquired".
        assert pt.try_acquire() is True
