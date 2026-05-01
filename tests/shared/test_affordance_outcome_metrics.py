"""Tests for the affordance outcome Prometheus counter.

Pairs with ``test_affordance_recruitment_metrics``. Cardinality is
hard-bounded to two labels (success / failure); no caller can introduce
a third.
"""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from shared.affordance_metrics import AffordanceMetrics  # noqa: E402
from shared.affordance_outcome_metrics import (  # noqa: E402
    OUTCOME_LABELS,
    outcome_counter_value,
    record_outcome,
)

# ── Cardinality bound ───────────────────────────────────────────────────


class TestCardinalityBound:
    def test_outcome_labels_is_pair(self) -> None:
        assert OUTCOME_LABELS == ("success", "failure")
        assert len(OUTCOME_LABELS) == 2


# ── record_outcome direct ───────────────────────────────────────────────


class TestRecordOutcomeDirect:
    def test_success_increments_success_label(self) -> None:
        before = outcome_counter_value("success") or 0.0
        record_outcome(True)
        after = outcome_counter_value("success") or 0.0
        assert after - before == 1

    def test_failure_increments_failure_label(self) -> None:
        before = outcome_counter_value("failure") or 0.0
        record_outcome(False)
        after = outcome_counter_value("failure") or 0.0
        assert after - before == 1

    def test_success_does_not_touch_failure_count(self) -> None:
        before_fail = outcome_counter_value("failure") or 0.0
        record_outcome(True)
        record_outcome(True)
        after_fail = outcome_counter_value("failure") or 0.0
        assert after_fail - before_fail == 0

    def test_failure_does_not_touch_success_count(self) -> None:
        before_success = outcome_counter_value("success") or 0.0
        record_outcome(False)
        record_outcome(False)
        after_success = outcome_counter_value("success") or 0.0
        assert after_success - before_success == 0


# ── AffordanceMetrics wire-in ───────────────────────────────────────────


class TestAffordanceMetricsWiring:
    """Confirm AffordanceMetrics.record_outcome increments the counter."""

    def test_record_outcome_increments_counter(self) -> None:
        metrics = AffordanceMetrics()

        before_s = outcome_counter_value("success") or 0.0
        before_f = outcome_counter_value("failure") or 0.0

        metrics.record_outcome("env.weather_conditions", success=True)
        metrics.record_outcome("env.weather_conditions", success=False)
        metrics.record_outcome("studio.compose_camera_grid", success=True)

        after_s = outcome_counter_value("success") or 0.0
        after_f = outcome_counter_value("failure") or 0.0

        assert after_s - before_s == 2
        assert after_f - before_f == 1

    def test_record_outcome_still_appends_event_list(self) -> None:
        """The new wire must not break the existing in-memory event list."""

        metrics = AffordanceMetrics()
        metrics.record_outcome("env.weather_conditions", success=True)
        metrics.record_outcome("env.weather_conditions", success=False)

        # Internal — pinned because the public summary depends on it.
        assert len(metrics._outcomes) == 2
        assert metrics._outcomes[0].success is True
        assert metrics._outcomes[1].success is False

    def test_compute_summary_unchanged_after_wire(self) -> None:
        metrics = AffordanceMetrics()
        metrics.record_outcome("env.weather_conditions", success=True)
        metrics.record_outcome("env.weather_conditions", success=False)
        summary = metrics.compute_summary()
        # Whatever shape compute_summary returns, the wire must not crash it.
        assert isinstance(summary, dict)


# ── Source-level pin ────────────────────────────────────────────────────


class TestSourceWire:
    def test_record_outcome_method_calls_helper(self) -> None:
        from pathlib import Path

        source = Path("shared/affordance_metrics.py").read_text(encoding="utf-8")
        idx = source.index("def record_outcome")
        slice_after = source[idx : idx + 1500]
        assert "affordance_outcome_metrics" in slice_after, (
            "record_outcome must import from affordance_outcome_metrics for the wire to fire"
        )
