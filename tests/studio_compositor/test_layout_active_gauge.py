"""Tests for cc-task u6-four-layouts-switching-followup.

Pin the contract introduced in this PR:

  HAPAX_COMPOSITOR_LAYOUT_ACTIVE{layout=NAME} = 1.0 when NAME is the
  active layout, 0.0 otherwise. LayoutStore.set_active() updates the
  gauge atomically — the previous label set drops to 0, the new one
  rises to 1.

The gauge is the dashboard query for "which layout is currently
active". The audit U6 acceptance criterion asked for evidence that
all 4 declared layouts are reachable; the gauge gives that evidence
on a 10-min sample window via PromQL `count_values_over_time`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def _ensure_repo_on_path():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    yield


@pytest.fixture
def fresh_metrics():
    """Re-initialise the studio_compositor metrics module so each test
    starts from a clean prometheus registry. Required because the gauge
    is module-level state."""
    from agents.studio_compositor import metrics

    metrics._init_metrics()
    return metrics


@pytest.fixture
def layout_store(tmp_path: Path):
    """Build a LayoutStore with two synthetic layouts on disk so the
    set_active path can exercise the gauge update without depending on
    config/compositor-layouts/*.json shipping any specific contents."""
    import json

    from agents.studio_compositor.layout_loader import LayoutStore

    (tmp_path / "alpha.json").write_text(
        json.dumps(
            {
                "name": "alpha",
                "description": "synthetic test layout",
                "sources": [],
                "assignments": [],
                "surfaces": [],
            }
        )
    )
    (tmp_path / "beta.json").write_text(
        json.dumps(
            {
                "name": "beta",
                "description": "synthetic test layout",
                "sources": [],
                "assignments": [],
                "surfaces": [],
            }
        )
    )
    store = LayoutStore(layout_dir=tmp_path)
    return store


class TestLayoutActiveGauge:
    def test_set_active_marks_target_layout_as_one(self, fresh_metrics, layout_store) -> None:
        assert layout_store.set_active("alpha") is True
        gauge = fresh_metrics.HAPAX_COMPOSITOR_LAYOUT_ACTIVE
        assert gauge is not None, "HAPAX_COMPOSITOR_LAYOUT_ACTIVE not initialised"
        # Per-label value via internal _value attribute (Counter / Gauge
        # both expose it). prometheus_client doesn't have a public per-
        # label getter, so this reads the single-process state directly.
        sample = gauge.labels(layout="alpha")._value.get()
        assert sample == 1.0

    def test_swap_drops_previous_to_zero(self, fresh_metrics, layout_store) -> None:
        layout_store.set_active("alpha")
        layout_store.set_active("beta")
        gauge = fresh_metrics.HAPAX_COMPOSITOR_LAYOUT_ACTIVE
        assert gauge.labels(layout="alpha")._value.get() == 0.0
        assert gauge.labels(layout="beta")._value.get() == 1.0

    def test_failed_set_active_does_not_touch_gauge(self, fresh_metrics, layout_store) -> None:
        """A request for a non-existent layout returns False; the gauge
        must not move."""
        layout_store.set_active("alpha")
        before = fresh_metrics.HAPAX_COMPOSITOR_LAYOUT_ACTIVE.labels(layout="alpha")._value.get()
        assert layout_store.set_active("nonexistent-layout") is False
        after = fresh_metrics.HAPAX_COMPOSITOR_LAYOUT_ACTIVE.labels(layout="alpha")._value.get()
        assert before == after == 1.0

    def test_set_active_returns_true_even_when_metrics_uninitialised(self, layout_store) -> None:
        """If init_metrics() hasn't run (CI/test environment without
        prometheus_client), set_active must still return True. The
        metrics update is best-effort, never load-bearing."""
        # Don't request the fresh_metrics fixture; module-level gauge
        # may be None or stale. Either way: the layout switch must work.
        assert layout_store.set_active("alpha") is True


class TestU6AcceptanceMapping:
    def test_gauge_metric_name_matches_acceptance_criterion(self, fresh_metrics) -> None:
        """U6 acceptance asked for ``hapax_compositor_layout_active`` —
        pin the canonical metric name to catch a future rename."""
        gauge = fresh_metrics.HAPAX_COMPOSITOR_LAYOUT_ACTIVE
        assert gauge is not None
        assert gauge._name == "hapax_compositor_layout_active"
