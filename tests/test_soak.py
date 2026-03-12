"""Tests for the soak period manager."""

from __future__ import annotations

import time
from pathlib import Path

from shared.soak import SoakManager


class TestSoakManager:
    def test_register_and_active(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore", soak_minutes=30)
        active = mgr.active_entries()
        assert len(active) == 1
        assert active[0].pr_number == 42

    def test_record_healthy_check(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore")
        degraded = mgr.record_health_check(healthy=True)
        assert len(degraded) == 0
        assert mgr.active_entries()[0].checks_passed == 1

    def test_record_unhealthy_returns_degraded(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore")
        degraded = mgr.record_health_check(healthy=False)
        assert len(degraded) == 1
        assert degraded[0].pr_number == 42

    def test_mark_reverted(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore")
        mgr.mark_reverted(42)
        assert len(mgr.active_entries()) == 0

    def test_complete_soak(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore")
        mgr.complete_soak(42)
        assert len(mgr.active_entries()) == 0

    def test_complete_expired(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore", soak_minutes=0)
        # soak_minutes=0 means soak_until is in the past.
        time.sleep(0.01)
        completed = mgr.complete_expired()
        assert len(completed) == 1
        assert completed[0].pr_number == 42

    def test_persistence(self, tmp_path: Path):
        state_path = tmp_path / "soak.json"
        mgr1 = SoakManager(state_path=state_path)
        mgr1.register_merge(42, "agent/issue-42", "chore")

        mgr2 = SoakManager(state_path=state_path)
        assert len(mgr2.active_entries()) == 1

    def test_multiple_entries(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore")
        mgr.register_merge(43, "agent/issue-43", "bug")
        assert len(mgr.active_entries()) == 2

    def test_cleanup_old(self, tmp_path: Path):
        mgr = SoakManager(state_path=tmp_path / "soak.json")
        mgr.register_merge(42, "agent/issue-42", "chore")
        mgr.complete_soak(42)
        # Backdate the entry.
        mgr._entries[0].merged_at = time.time() - 100 * 86400
        mgr.cleanup(max_age_days=30)
        assert len(mgr._entries) == 0
