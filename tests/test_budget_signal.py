"""Tests for the compositor degraded-signal publisher (Followup F3).

Bridges Phase 7's BudgetTracker to the stimmung dimension pipeline
by writing a JSON signal file the VLA can subscribe to.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.studio_compositor.budget import BudgetTracker
from agents.studio_compositor.budget_signal import (
    DEFAULT_SIGNAL_PATH,
    build_degraded_signal,
    publish_degraded_signal,
)

# ---------------------------------------------------------------------------
# build_degraded_signal — pure function over a tracker snapshot
# ---------------------------------------------------------------------------


def test_build_signal_empty_tracker():
    tracker = BudgetTracker()
    payload = build_degraded_signal(tracker)
    assert payload["total_skip_count"] == 0
    assert payload["degraded_source_count"] == 0
    assert payload["total_active_sources"] == 0
    assert payload["per_source"] == {}
    assert payload["worst_source"] is None


def test_build_signal_with_one_recorded_source_no_skips():
    tracker = BudgetTracker()
    tracker.record("alpha", 5.0)
    payload = build_degraded_signal(tracker)
    assert payload["total_active_sources"] == 1
    assert payload["degraded_source_count"] == 0
    assert payload["total_skip_count"] == 0
    assert payload["worst_source"] is None
    assert payload["per_source"]["alpha"]["skip_count"] == 0
    assert payload["per_source"]["alpha"]["last_ms"] == 5.0


def test_build_signal_marks_skip_only_source_as_degraded():
    tracker = BudgetTracker()
    tracker.record_skip("hot")
    tracker.record_skip("hot")
    payload = build_degraded_signal(tracker)
    assert payload["total_skip_count"] == 2
    assert payload["degraded_source_count"] == 1
    assert payload["worst_source"] is not None
    assert payload["worst_source"]["source_id"] == "hot"
    assert payload["worst_source"]["skip_count"] == 2


def test_build_signal_picks_highest_skip_count_as_worst():
    """Multiple degraded sources → worst is the one with the most skips."""
    tracker = BudgetTracker()
    tracker.record("good", 1.0)
    for _ in range(3):
        tracker.record_skip("medium")
    for _ in range(8):
        tracker.record_skip("worst")
    payload = build_degraded_signal(tracker)
    assert payload["degraded_source_count"] == 2
    assert payload["worst_source"]["source_id"] == "worst"
    assert payload["worst_source"]["skip_count"] == 8


def test_build_signal_per_source_includes_every_source():
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    tracker.record("b", 2.0)
    tracker.record_skip("c")
    payload = build_degraded_signal(tracker)
    assert set(payload["per_source"].keys()) == {"a", "b", "c"}


def test_build_signal_rounds_ms_values():
    """Per-source ms values are rounded to 3 decimal places to keep
    the JSON readable."""
    tracker = BudgetTracker()
    tracker.record("a", 1.23456789)
    payload = build_degraded_signal(tracker)
    assert payload["per_source"]["a"]["last_ms"] == 1.235


def test_build_signal_total_active_sources_counts_every_recorded_source():
    """A source with skips but no samples still counts as active —
    it exists in the tracker."""
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    tracker.record_skip("b")
    payload = build_degraded_signal(tracker)
    assert payload["total_active_sources"] == 2


def test_build_signal_has_timestamp_ms_field():
    tracker = BudgetTracker()
    payload = build_degraded_signal(tracker)
    assert "timestamp_ms" in payload
    assert isinstance(payload["timestamp_ms"], (int, float))


# ---------------------------------------------------------------------------
# publish_degraded_signal — disk write
# ---------------------------------------------------------------------------


def test_publish_writes_json_at_path(tmp_path: Path):
    tracker = BudgetTracker()
    tracker.record("a", 4.0)
    tracker.record_skip("b")
    out = tmp_path / "degraded.json"
    publish_degraded_signal(tracker, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["total_skip_count"] == 1
    assert data["degraded_source_count"] == 1
    assert "a" in data["per_source"]
    assert "b" in data["per_source"]


def test_publish_creates_parent_directory(tmp_path: Path):
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    nested = tmp_path / "deep" / "subdir" / "degraded.json"
    publish_degraded_signal(tracker, nested)
    assert nested.is_file()


def test_publish_atomic_write_no_tmp_left_behind(tmp_path: Path):
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    out = tmp_path / "degraded.json"
    publish_degraded_signal(tracker, out)
    tmp_marker = out.with_suffix(out.suffix + ".tmp")
    assert not tmp_marker.exists()
    assert out.is_file()


def test_publish_returns_target_path(tmp_path: Path):
    tracker = BudgetTracker()
    out = tmp_path / "degraded.json"
    result = publish_degraded_signal(tracker, out)
    assert result == out


def test_default_signal_path_is_under_dev_shm():
    """The canonical signal path lives under /dev/shm so the VLA
    polls a tmpfs location with no disk overhead."""
    assert str(DEFAULT_SIGNAL_PATH).startswith("/dev/shm/")


def test_publish_replaces_existing_file(tmp_path: Path):
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    out = tmp_path / "degraded.json"
    publish_degraded_signal(tracker, out)

    # Tracker state changes; publish again with new payload.
    tracker.record_skip("a")
    publish_degraded_signal(tracker, out)
    data = json.loads(out.read_text())
    assert data["total_skip_count"] == 1


# ---------------------------------------------------------------------------
# End-to-end smoke
# ---------------------------------------------------------------------------


def test_publish_degraded_marks_freshness_gauge_on_success(tmp_path: Path):
    """Follow-up #6: a successful publish_degraded_signal call marks
    the module-level FreshnessGauge so the health monitor can see the
    heartbeat.
    """
    from agents.studio_compositor import budget_signal as signal_mod

    gauge = signal_mod._PUBLISH_DEGRADED_FRESHNESS
    assert gauge is not None, "module-level freshness gauge should be constructed at import"
    tracker = BudgetTracker()
    tracker.record("alpha", 1.0)
    publish_degraded_signal(tracker, tmp_path / "degraded.json")
    assert not gauge.is_stale(tolerance_mult=60), (
        "publish_degraded_signal should have marked the freshness gauge fresh"
    )


def test_publish_degraded_marks_freshness_failed_on_write_error(tmp_path: Path):
    """Follow-up #6: a failing publish_degraded_signal marks the gauge
    as failed before re-raising so the failure counter increments.
    """
    from agents.studio_compositor import budget_signal as signal_mod

    gauge = signal_mod._PUBLISH_DEGRADED_FRESHNESS
    assert gauge is not None
    tracker = BudgetTracker()
    tracker.record("alpha", 1.0)
    with patch(
        "agents.studio_compositor.budget_signal.atomic_write_json",
        side_effect=OSError("disk full"),
    ):
        with pytest.raises(OSError, match="disk full"):
            publish_degraded_signal(tracker, tmp_path / "degraded.json")


def test_realistic_compositor_signal(tmp_path: Path):
    """Sanity: a tracker with mixed source health writes a signal
    that captures all the relevant fields."""
    tracker = BudgetTracker()
    # Three healthy sources
    for source in ("cam-brio", "cam-c920", "sierpinski"):
        for v in (3.0, 4.0, 5.0):
            tracker.record(source, v)
    # Two degraded sources
    for _ in range(5):
        tracker.record_skip("album-overlay")
    for _ in range(2):
        tracker.record_skip("token-pole")
    out = tmp_path / "degraded.json"
    publish_degraded_signal(tracker, out)
    data = json.loads(out.read_text())
    assert data["total_active_sources"] == 5
    assert data["degraded_source_count"] == 2
    assert data["total_skip_count"] == 7
    assert data["worst_source"]["source_id"] == "album-overlay"
    assert data["worst_source"]["skip_count"] == 5
    # Healthy sources are present but not flagged.
    for healthy in ("cam-brio", "cam-c920", "sierpinski"):
        assert data["per_source"][healthy]["skip_count"] == 0
