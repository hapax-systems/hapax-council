"""Tests for the Phase 7 budget enforcement system.

Covers:

- BudgetTracker rolling window + percentile + over-budget queries
- publish_costs JSON snapshot writer (atomic)
- CairoSourceRunner integration with the tracker (record + skip)

The integration tests instantiate the runner with a recording test
source and verify that:

- The tracker receives one record() call per successful tick when
  wired up; zero calls when no tracker is supplied.
- An over-budget previous frame causes the next tick to be skipped
  (no render, no record), the cached surface stays in place, and
  the consecutive_skips counter increments.
- A successful render clears the skip run.
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

import pytest

from agents.studio_compositor.budget import (
    DEFAULT_WINDOW_SIZE,
    BudgetTracker,
    SourceCost,
    publish_costs,
)
from agents.studio_compositor.cairo_source import CairoSource, CairoSourceRunner

if TYPE_CHECKING:
    from pathlib import Path

    import cairo

# ---------------------------------------------------------------------------
# BudgetTracker basics
# ---------------------------------------------------------------------------


def test_record_appends_to_window():
    tracker = BudgetTracker(window_size=10)
    tracker.record("a", 1.0)
    tracker.record("a", 2.0)
    tracker.record("a", 3.0)
    assert tracker.last_frame_ms("a") == 3.0
    assert tracker.avg_frame_ms("a") == pytest.approx(2.0)


def test_record_zero_samples_returns_zero():
    tracker = BudgetTracker()
    assert tracker.last_frame_ms("nope") == 0.0
    assert tracker.avg_frame_ms("nope") == 0.0
    assert tracker.p95_frame_ms("nope") == 0.0


def test_last_frame_ms_returns_most_recent():
    tracker = BudgetTracker(window_size=5)
    for v in (10.0, 20.0, 5.0, 15.0):
        tracker.record("a", v)
    assert tracker.last_frame_ms("a") == 15.0


def test_avg_frame_ms_smooths_across_window():
    tracker = BudgetTracker(window_size=4)
    for v in (1.0, 2.0, 3.0, 4.0):
        tracker.record("a", v)
    assert tracker.avg_frame_ms("a") == pytest.approx(2.5)


def test_p95_frame_ms_picks_high_percentile():
    """For a 10-sample window, p95 should sit near the maximum."""
    tracker = BudgetTracker(window_size=10)
    for v in range(1, 11):  # 1, 2, ..., 10
        tracker.record("a", float(v))
    p95 = tracker.p95_frame_ms("a")
    # Linear-interpolated p95 of [1..10] is 9.55.
    assert p95 == pytest.approx(9.55, abs=0.05)


def test_window_evicts_oldest_after_max_size():
    tracker = BudgetTracker(window_size=3)
    for v in (1.0, 2.0, 3.0, 4.0, 5.0):
        tracker.record("a", v)
    # Only the last 3 samples should remain.
    assert tracker.avg_frame_ms("a") == pytest.approx(4.0)  # (3+4+5)/3


def test_record_unknown_source_creates_entry():
    tracker = BudgetTracker()
    tracker.record("brand_new", 7.5)
    assert tracker.last_frame_ms("brand_new") == 7.5
    assert "brand_new" in tracker.snapshot()


def test_default_window_size_constant():
    tracker = BudgetTracker()
    assert tracker.window_size == DEFAULT_WINDOW_SIZE


def test_zero_window_size_rejected():
    with pytest.raises(ValueError):
        BudgetTracker(window_size=0)


def test_reset_one_source_clears_only_that_source():
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    tracker.record("b", 2.0)
    tracker.reset("a")
    assert tracker.last_frame_ms("a") == 0.0
    assert tracker.last_frame_ms("b") == 2.0


def test_reset_all_clears_every_source():
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    tracker.record("b", 2.0)
    tracker.reset()
    assert tracker.snapshot() == {}


def test_concurrent_record_is_thread_safe():
    """Many threads recording into the same tracker must not race."""
    tracker = BudgetTracker(window_size=1000)
    errors: list[BaseException] = []

    def worker(source_id: str, n: int) -> None:
        try:
            for i in range(n):
                tracker.record(source_id, float(i))
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("a", 200)),
        threading.Thread(target=worker, args=("a", 200)),
        threading.Thread(target=worker, args=("b", 200)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    assert not errors
    snapshot = tracker.snapshot()
    # All 400 samples for "a" landed (no lost writes).
    assert snapshot["a"].sample_count == 400
    assert snapshot["b"].sample_count == 200


# ---------------------------------------------------------------------------
# Over-budget query
# ---------------------------------------------------------------------------


def test_over_budget_false_when_no_samples():
    """First frame after init never trips the budget — operator gets one image."""
    tracker = BudgetTracker()
    assert tracker.over_budget("never_recorded", budget_ms=0.001) is False


def test_over_budget_false_when_last_frame_within_budget():
    tracker = BudgetTracker()
    tracker.record("a", 3.0)
    assert tracker.over_budget("a", budget_ms=5.0) is False


def test_over_budget_true_when_last_frame_exceeds_budget():
    tracker = BudgetTracker()
    tracker.record("a", 7.5)
    assert tracker.over_budget("a", budget_ms=5.0) is True


def test_over_budget_uses_only_last_frame_not_average():
    """A spike on the most recent frame trips the budget even when the
    rolling average is well under it."""
    tracker = BudgetTracker(window_size=10)
    for _ in range(9):
        tracker.record("a", 1.0)  # avg drives toward 1ms
    tracker.record("a", 100.0)  # one big spike
    assert tracker.avg_frame_ms("a") < 50.0
    assert tracker.over_budget("a", budget_ms=10.0) is True


# ---------------------------------------------------------------------------
# Snapshot + publish
# ---------------------------------------------------------------------------


def test_snapshot_returns_per_source_cost():
    tracker = BudgetTracker(window_size=4)
    tracker.record("a", 1.0)
    tracker.record("a", 2.0)
    tracker.record("b", 5.0)
    snap = tracker.snapshot()
    assert isinstance(snap["a"], SourceCost)
    assert snap["a"].source_id == "a"
    assert snap["a"].sample_count == 2
    assert snap["a"].last_ms == 2.0
    assert snap["a"].avg_ms == pytest.approx(1.5)
    assert snap["b"].sample_count == 1
    assert snap["b"].last_ms == 5.0


def test_snapshot_includes_skip_count():
    tracker = BudgetTracker()
    tracker.record_skip("a")
    tracker.record_skip("a")
    snap = tracker.snapshot()
    assert snap["a"].skip_count == 2
    # Skip-only sources have zero samples but the entry exists.
    assert snap["a"].sample_count == 0


def test_publish_costs_writes_json_atomically(tmp_path: Path):
    tracker = BudgetTracker()
    tracker.record("alpha", 1.5)
    tracker.record("beta", 7.25)
    tracker.record_skip("alpha")
    out = tmp_path / "costs.json"
    publish_costs(tracker, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert "alpha" in data
    assert data["alpha"]["last_ms"] == 1.5
    assert data["alpha"]["skip_count"] == 1
    assert data["beta"]["last_ms"] == 7.25


def test_publish_costs_creates_parent_directory(tmp_path: Path):
    tracker = BudgetTracker()
    tracker.record("a", 1.0)
    nested = tmp_path / "nested" / "dirs" / "costs.json"
    publish_costs(tracker, nested)
    assert nested.is_file()


# ---------------------------------------------------------------------------
# CairoSourceRunner integration
# ---------------------------------------------------------------------------


class _SimpleSource(CairoSource):
    """Test source: records render call count, draws a solid rect."""

    def __init__(self) -> None:
        self.calls = 0

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, object],
    ) -> None:
        self.calls += 1
        cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()


def test_runner_records_to_tracker_when_provided():
    tracker = BudgetTracker()
    src = _SimpleSource()
    runner = CairoSourceRunner(
        source_id="t",
        source=src,
        canvas_w=8,
        canvas_h=8,
        target_fps=10,
        budget_tracker=tracker,
    )
    runner.tick_once()
    runner.tick_once()
    runner.tick_once()
    snap = tracker.snapshot()
    assert snap["t"].sample_count == 3
    assert snap["t"].last_ms >= 0.0


def test_runner_no_record_when_tracker_is_none():
    """Default behavior: no tracker → nothing recorded anywhere global."""
    src = _SimpleSource()
    runner = CairoSourceRunner(
        source_id="no_tracker",
        source=src,
        canvas_w=8,
        canvas_h=8,
        target_fps=10,
    )
    runner.tick_once()
    # The runner still updates its private last_render_ms field.
    assert runner.last_render_ms >= 0.0
    assert src.calls == 1


def test_runner_skips_when_over_budget():
    """Phase 7b: a previous over-budget frame causes the next tick to skip."""
    tracker = BudgetTracker()
    # Pre-load a previous frame that exceeded the budget.
    tracker.record("hot", 50.0)
    src = _SimpleSource()
    runner = CairoSourceRunner(
        source_id="hot",
        source=src,
        canvas_w=8,
        canvas_h=8,
        target_fps=10,
        budget_tracker=tracker,
        budget_ms=5.0,
    )
    runner.tick_once()
    # The render() method must NOT have been called.
    assert src.calls == 0
    assert runner.consecutive_skips == 1
    assert runner.degraded is True
    snap = tracker.snapshot()
    assert snap["hot"].skip_count == 1


def test_runner_skip_preserves_cached_surface():
    """When a tick is skipped, the previous successful surface stays in place."""
    tracker = BudgetTracker()
    src = _SimpleSource()
    runner = CairoSourceRunner(
        source_id="warm",
        source=src,
        canvas_w=16,
        canvas_h=16,
        target_fps=10,
        budget_tracker=tracker,
        budget_ms=5.0,
    )
    # First tick: no previous samples → over_budget is False → render runs.
    runner.tick_once()
    cached = runner.get_output_surface()
    assert cached is not None
    assert src.calls == 1
    # Force the next tick to be over budget by injecting a fake big sample.
    tracker.record("warm", 100.0)
    runner.tick_once()
    # render() must NOT have been called this time, but the cached
    # surface from the first tick is still readable.
    assert src.calls == 1  # unchanged
    assert runner.consecutive_skips == 1
    assert runner.get_output_surface() is cached


def test_runner_consecutive_skips_track_degraded_count():
    """Multiple over-budget ticks accumulate the skip counter."""
    tracker = BudgetTracker()
    tracker.record("slow", 50.0)
    src = _SimpleSource()
    runner = CairoSourceRunner(
        source_id="slow",
        source=src,
        canvas_w=4,
        canvas_h=4,
        target_fps=10,
        budget_tracker=tracker,
        budget_ms=1.0,
    )
    runner.tick_once()
    runner.tick_once()
    runner.tick_once()
    assert runner.consecutive_skips == 3
    assert tracker.snapshot()["slow"].skip_count == 3
    assert src.calls == 0


def test_runner_degraded_clears_after_successful_render():
    """A successful render resets the consecutive-skip run."""
    tracker = BudgetTracker()
    # Force the first tick to skip by pre-loading an over-budget sample.
    tracker.record("recoverable", 50.0)
    src = _SimpleSource()
    runner = CairoSourceRunner(
        source_id="recoverable",
        source=src,
        canvas_w=8,
        canvas_h=8,
        target_fps=10,
        budget_tracker=tracker,
        budget_ms=5.0,
    )
    runner.tick_once()  # skipped
    assert runner.consecutive_skips == 1
    # Now reset the tracker so the next tick has no samples → renders.
    tracker.reset("recoverable")
    runner.tick_once()
    assert src.calls == 1
    assert runner.consecutive_skips == 0
    assert runner.degraded is False


def test_runner_rejects_invalid_budget_ms():
    src = _SimpleSource()
    with pytest.raises(ValueError):
        CairoSourceRunner(
            source_id="t",
            source=src,
            target_fps=10,
            budget_ms=0.0,
        )


# ---------------------------------------------------------------------------
# Followup F2: per-frame layout budgets
# ---------------------------------------------------------------------------


def test_total_last_frame_ms_sums_across_active_sources():
    tracker = BudgetTracker()
    tracker.record("a", 2.0)
    tracker.record("b", 3.5)
    tracker.record("c", 1.25)
    assert tracker.total_last_frame_ms() == pytest.approx(6.75)


def test_total_last_frame_ms_filters_by_source_ids():
    """When source_ids is supplied, only those sources contribute."""
    tracker = BudgetTracker()
    tracker.record("a", 2.0)
    tracker.record("b", 3.5)
    tracker.record("c", 99.0)  # not in the active list
    total = tracker.total_last_frame_ms(["a", "b"])
    assert total == pytest.approx(5.5)


def test_total_last_frame_ms_unrecorded_source_contributes_zero():
    tracker = BudgetTracker()
    tracker.record("a", 4.0)
    # "ghost" was never recorded; it adds 0.0 instead of raising.
    total = tracker.total_last_frame_ms(["a", "ghost"])
    assert total == pytest.approx(4.0)


def test_total_last_frame_ms_empty_tracker_returns_zero():
    tracker = BudgetTracker()
    assert tracker.total_last_frame_ms() == 0.0
    assert tracker.total_last_frame_ms(["a", "b"]) == 0.0


def test_total_avg_frame_ms_sums_rolling_averages():
    tracker = BudgetTracker(window_size=4)
    # a: avg = 2.0
    for v in (1.0, 2.0, 3.0):
        tracker.record("a", v)
    # b: avg = 5.0
    tracker.record("b", 5.0)
    total = tracker.total_avg_frame_ms()
    assert total == pytest.approx(7.0)


def test_over_layout_budget_false_when_under():
    tracker = BudgetTracker()
    tracker.record("a", 2.0)
    tracker.record("b", 3.0)
    assert tracker.over_layout_budget(layout_budget_ms=10.0) is False


def test_over_layout_budget_true_when_total_exceeds():
    tracker = BudgetTracker()
    tracker.record("a", 5.0)
    tracker.record("b", 6.0)
    assert tracker.over_layout_budget(layout_budget_ms=10.0) is True


def test_over_layout_budget_false_when_no_samples():
    """First frame after init never trips the budget — operator gets at
    least one image regardless of layout cost."""
    tracker = BudgetTracker()
    assert tracker.over_layout_budget(layout_budget_ms=0.001) is False


def test_over_layout_budget_filters_by_source_ids():
    tracker = BudgetTracker()
    tracker.record("active1", 4.0)
    tracker.record("active2", 4.0)
    tracker.record("hidden", 100.0)  # culled this frame
    # When we only count active sources, total = 8.0 < budget 10.0.
    assert tracker.over_layout_budget(10.0, ["active1", "active2"]) is False
    # If we naively summed every recorded source, total = 108.0 > 10.
    assert tracker.over_layout_budget(10.0) is True


def test_headroom_ms_positive_when_under_budget():
    tracker = BudgetTracker()
    tracker.record("a", 2.0)
    tracker.record("b", 3.0)
    assert tracker.headroom_ms(layout_budget_ms=10.0) == pytest.approx(5.0)


def test_headroom_ms_negative_when_over_budget():
    tracker = BudgetTracker()
    tracker.record("a", 8.0)
    tracker.record("b", 8.0)
    headroom = tracker.headroom_ms(layout_budget_ms=10.0)
    assert headroom == pytest.approx(-6.0)


def test_headroom_ms_equals_full_budget_when_no_samples():
    """An empty tracker has full headroom available — every ms of the
    budget is available for the first frame."""
    tracker = BudgetTracker()
    assert tracker.headroom_ms(layout_budget_ms=16.7) == pytest.approx(16.7)


def test_layout_budget_uses_last_not_avg_for_spike_detection():
    """Spike detection: a single bad frame trips the layout budget
    even when the rolling avg would not."""
    tracker = BudgetTracker(window_size=10)
    for _ in range(9):
        tracker.record("a", 1.0)
    tracker.record("a", 50.0)  # spike on the most recent frame
    # avg = (9*1.0 + 50.0) / 10 = 5.9, well under 10ms budget
    assert tracker.total_avg_frame_ms() < 10.0
    # But the most recent frame is 50ms, way over budget
    assert tracker.over_layout_budget(layout_budget_ms=10.0) is True
